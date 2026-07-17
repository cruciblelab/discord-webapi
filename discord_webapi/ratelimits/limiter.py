"""`GuildRateLimiter` -- a per-guild, dashboard-configurable, live-updating
rate limiter, usable anywhere in your own code, not just tied to a
discord.py `Command` object the way `CommandRegistry`'s cooldowns are.

Same architectural pattern as `CommandRegistry`: a `RateLimitStore`
(Memory/SQL) for persistence, a `Transport` event
(`ratelimit_config_changed`) for restart-free live updates across
processes, and an in-memory token-bucket cache kept warm so `.check()`
never does a per-call DB read -- but keyed by an arbitrary `key` string
you choose, not a command name, so you can rate-limit anything: an
automod check, a webhook handler, a hand-written command that never goes
through `CommandRegistry` at all, or several of these things sharing one
guild-configurable threshold.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from discord_webapi.ratelimits.events import (
    EVENT_TYPE_RATELIMIT_CONFIG_CHANGED,
    RateLimitConfigChanged,
)
from discord_webapi.ratelimits.models import RateLimitRule
from discord_webapi.storage.base import RateLimitStore
from discord_webapi.transport.base import Event, Transport


class GuildRateLimiter:
    """`await limiter.check(guild_id, "automod.spam")` -- returns `True`
    (and consumes a token) if the call is allowed, `False` if this guild
    is currently over its configured rate for `key`. Pass `sub_key` (e.g.
    a Discord user id) to give each sub-key its own independent bucket
    while still sharing one guild-configurable threshold -- exactly what
    "5 messages per 10 seconds, per member" needs: one dashboard-editable
    rule (`guild_id`, `key`), many buckets (one per member).

    Falls back to `default_max_calls`/`default_per_seconds` for any
    `(guild_id, key)` with no explicit `RateLimitRule` on file --
    `set_rule()`/the dashboard API only ever need to write an override
    for guilds that want something different from your library/bot's
    own sane default.
    """

    def __init__(
        self,
        transport: Transport,
        store: RateLimitStore,
        *,
        default_max_calls: int = 5,
        default_per_seconds: float = 10.0,
        bucket_idle_ttl_seconds: float = 3600.0,
        bucket_sweep_interval: int = 2000,
    ) -> None:
        self.transport = transport
        self.store = store
        # Identifies events this exact instance published, so its own
        # `_on_config_changed` subscription (see below) can tell "another
        # process/instance changed this rule" apart from "I just changed
        # this rule myself, synchronously, a moment ago" -- see the
        # docstring on `_on_config_changed` for why that distinction
        # matters.
        self._instance_id = uuid.uuid4().hex
        self._default_max_calls = default_max_calls
        self._default_per_seconds = default_per_seconds
        self._rules: dict[tuple[int, str], RateLimitRule] = {}
        self._loaded: set[tuple[int, str]] = set()
        self._buckets: dict[tuple[int, str, str], tuple[float, float]] = {}
        # `sub_key` is documented for per-member buckets (module docstring),
        # which means one dict entry per distinct (guild_id, key, user_id)
        # ever seen -- with no eviction, that's an unbounded leak for the
        # lifetime of the process. A bucket idle longer than
        # `bucket_idle_ttl_seconds` is always fully refilled anyway (capped
        # at max_calls), so dropping it is behaviorally identical to keeping
        # it -- just frees memory. Swept every `bucket_sweep_interval` calls
        # rather than every call, to keep the hot path O(1) amortized.
        self._bucket_idle_ttl_seconds = bucket_idle_ttl_seconds
        self._bucket_sweep_interval = bucket_sweep_interval
        self._checks_since_sweep = 0

        transport.subscribe(EVENT_TYPE_RATELIMIT_CONFIG_CHANGED, self._on_config_changed)

    async def check(self, guild_id: int, key: str, *, sub_key: str = "_") -> bool:
        max_calls, per_seconds = await self._effective_limits(guild_id, key)

        bucket_key = (guild_id, key, sub_key)
        now = time.monotonic()
        tokens, last_refill = self._buckets.get(bucket_key, (float(max_calls), now))
        refill_rate = max_calls / per_seconds
        tokens = min(max_calls, tokens + (now - last_refill) * refill_rate)

        if tokens < 1:
            self._buckets[bucket_key] = (tokens, now)
            allowed = False
        else:
            self._buckets[bucket_key] = (tokens - 1, now)
            allowed = True

        self._checks_since_sweep += 1
        if self._checks_since_sweep >= self._bucket_sweep_interval:
            self._sweep_idle_buckets(now)

        return allowed

    def _sweep_idle_buckets(self, now: float) -> None:
        self._checks_since_sweep = 0
        stale_cutoff = now - self._bucket_idle_ttl_seconds
        for bucket_key, (_tokens, last_refill) in list(self._buckets.items()):
            if last_refill < stale_cutoff:
                del self._buckets[bucket_key]

    async def get_rule(self, guild_id: int, key: str) -> RateLimitRule | None:
        return await self._get_cached_rule(guild_id, key)

    async def list_rules(self, guild_id: int) -> list[RateLimitRule]:
        return await self.store.get_all_rules(guild_id)

    async def set_rule(
        self,
        guild_id: int,
        key: str,
        *,
        max_calls: int,
        per_seconds: float,
        updated_by_user_id: int | None = None,
    ) -> RateLimitRule:
        # Belt-and-suspenders: the dashboard API validates this too
        # (`RateLimitRulePatch`'s `Field(gt=0)`), but `set_rule()` is public
        # and callable directly (automod, a skeleton, your own code) without
        # going through the API layer -- and `check()`'s token-bucket math
        # divides by `per_seconds`, so a 0 here is a `ZeroDivisionError` on
        # every future call for this (guild_id, key) until fixed by hand.
        if max_calls <= 0:
            raise ValueError(f"max_calls must be > 0, got {max_calls!r}")
        if per_seconds <= 0:
            raise ValueError(f"per_seconds must be > 0, got {per_seconds!r}")
        rule = RateLimitRule(
            guild_id=guild_id,
            key=key,
            max_calls=max_calls,
            per_seconds=per_seconds,
            updated_at=datetime.now(UTC),
            updated_by_user_id=updated_by_user_id,
        )
        await self.store.set_rule(rule)
        self._cache_rule(rule)
        self._reset_buckets(guild_id, key)
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_RATELIMIT_CONFIG_CHANGED,
                payload=RateLimitConfigChanged(
                    guild_id=guild_id, key=key, origin_instance_id=self._instance_id
                ).model_dump(),
            )
        )
        return rule

    async def delete_rule(self, guild_id: int, key: str) -> None:
        await self.store.delete_rule(guild_id, key)
        self._invalidate(guild_id, key)
        self._reset_buckets(guild_id, key)
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_RATELIMIT_CONFIG_CHANGED,
                payload=RateLimitConfigChanged(
                    guild_id=guild_id, key=key, origin_instance_id=self._instance_id
                ).model_dump(),
            )
        )

    async def _effective_limits(self, guild_id: int, key: str) -> tuple[int, float]:
        rule = await self._get_cached_rule(guild_id, key)
        if rule is None:
            return self._default_max_calls, self._default_per_seconds
        return rule.max_calls, rule.per_seconds

    async def _get_cached_rule(self, guild_id: int, key: str) -> RateLimitRule | None:
        cache_key = (guild_id, key)
        if cache_key in self._loaded:
            return self._rules.get(cache_key)
        rule = await self.store.get_rule(guild_id, key)
        if rule is not None:
            self._rules[cache_key] = rule
        self._loaded.add(cache_key)
        return rule

    def _cache_rule(self, rule: RateLimitRule) -> None:
        cache_key = (rule.guild_id, rule.key)
        self._rules[cache_key] = rule
        self._loaded.add(cache_key)

    def _invalidate(self, guild_id: int, key: str) -> None:
        cache_key = (guild_id, key)
        self._rules.pop(cache_key, None)
        self._loaded.discard(cache_key)

    def _reset_buckets(self, guild_id: int, key: str) -> None:
        # A changed threshold should apply immediately, not blend with
        # whatever partial token count was left over under the old rule.
        for bucket_key in [bk for bk in self._buckets if bk[0] == guild_id and bk[1] == key]:
            del self._buckets[bucket_key]

    async def _on_config_changed(self, event: Event) -> None:
        """`set_rule`/`delete_rule` already invalidate the cache and reset
        this instance's own buckets synchronously, *before* publishing --
        but `InProcessTransport.publish()` fans out via
        `asyncio.create_task` (fire-and-forget), so this handler runs
        again later, asynchronously, for the very event this same
        instance just published. Between that synchronous reset and this
        handler finally running, a concurrent `check()` call may have
        already built fresh, legitimate bucket state under the new rule
        (e.g. its first token spend) -- redoing the reset here would wipe
        that out for free, handing whoever's mid-flight an extra unearned
        token. Skip it when this is our own echo; only a genuinely
        different process/instance's rule change needs to invalidate and
        reset *this* instance's state.
        """
        change = RateLimitConfigChanged.model_validate(event.payload)
        if change.origin_instance_id == self._instance_id:
            return
        self._invalidate(change.guild_id, change.key)
        self._reset_buckets(change.guild_id, change.key)
