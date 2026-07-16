import asyncio

import pytest

from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1
KEY = "automod.spam"


def _make_limiter(**kwargs: object) -> GuildRateLimiter:
    return GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), **kwargs)  # type: ignore[arg-type]


async def test_allows_up_to_the_default_limit_then_blocks() -> None:
    limiter = _make_limiter(default_max_calls=2, default_per_seconds=60.0)

    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is False


async def test_different_guilds_have_independent_buckets() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)

    assert await limiter.check(1, KEY) is True
    assert await limiter.check(2, KEY) is True


async def test_different_keys_have_independent_buckets() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)

    assert await limiter.check(GUILD_ID, "key-a") is True
    assert await limiter.check(GUILD_ID, "key-b") is True


async def test_sub_key_gives_independent_buckets_under_one_shared_rule() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)

    assert await limiter.check(GUILD_ID, KEY, sub_key="user-1") is True
    assert await limiter.check(GUILD_ID, KEY, sub_key="user-2") is True
    assert await limiter.check(GUILD_ID, KEY, sub_key="user-1") is False


async def test_set_rule_overrides_the_default_for_that_guild_and_key() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)

    await limiter.set_rule(GUILD_ID, KEY, max_calls=3, per_seconds=60.0)

    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is False


async def test_set_rule_does_not_affect_other_guilds() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)

    await limiter.set_rule(GUILD_ID, KEY, max_calls=99, per_seconds=60.0)

    assert await limiter.check(2, KEY) is True
    assert await limiter.check(2, KEY) is False


async def test_set_rule_resets_any_in_flight_bucket_state() -> None:
    """Tightening the threshold should apply immediately, not blend with
    whatever partial token count was left over under the old rule."""
    limiter = _make_limiter(default_max_calls=10, default_per_seconds=60.0)
    await limiter.check(GUILD_ID, KEY)  # consumes 1 of 10 under the default

    await limiter.set_rule(GUILD_ID, KEY, max_calls=1, per_seconds=60.0)

    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is False


async def test_delete_rule_reverts_to_the_default() -> None:
    limiter = _make_limiter(default_max_calls=1, default_per_seconds=60.0)
    await limiter.set_rule(GUILD_ID, KEY, max_calls=99, per_seconds=60.0)

    await limiter.delete_rule(GUILD_ID, KEY)

    assert await limiter.check(GUILD_ID, KEY) is True
    assert await limiter.check(GUILD_ID, KEY) is False


async def test_get_rule_returns_none_when_no_override_is_set() -> None:
    limiter = _make_limiter()

    assert await limiter.get_rule(GUILD_ID, KEY) is None


async def test_list_rules_returns_only_that_guilds_rules() -> None:
    limiter = _make_limiter()
    await limiter.set_rule(1, "a", max_calls=1, per_seconds=1.0)
    await limiter.set_rule(1, "b", max_calls=1, per_seconds=1.0)
    await limiter.set_rule(2, "a", max_calls=1, per_seconds=1.0)

    rules = await limiter.list_rules(1)

    assert {r.key for r in rules} == {"a", "b"}


async def test_set_rule_rejects_zero_or_negative_max_calls() -> None:
    """`check()`'s token-bucket math divides by per_seconds -- a 0/negative
    max_calls or per_seconds would either make the limiter always block or
    raise ZeroDivisionError on every future call for this (guild, key)."""
    limiter = _make_limiter()

    with pytest.raises(ValueError, match="max_calls"):
        await limiter.set_rule(GUILD_ID, KEY, max_calls=0, per_seconds=60.0)


async def test_set_rule_rejects_zero_or_negative_per_seconds() -> None:
    limiter = _make_limiter()

    with pytest.raises(ValueError, match="per_seconds"):
        await limiter.set_rule(GUILD_ID, KEY, max_calls=5, per_seconds=0.0)


async def test_idle_buckets_are_swept_to_bound_memory() -> None:
    """`sub_key` gives one bucket per (guild, key, user) ever seen -- without
    eviction, that's an unbounded memory leak for the life of the process."""
    limiter = _make_limiter(
        default_max_calls=1,
        default_per_seconds=60.0,
        bucket_idle_ttl_seconds=0.05,
        bucket_sweep_interval=2,
    )

    await limiter.check(GUILD_ID, KEY, sub_key="user-1")
    await asyncio.sleep(0.15)  # user-1's bucket is now idle past the ttl
    await limiter.check(GUILD_ID, KEY, sub_key="user-2")  # 2nd call triggers the sweep

    assert (GUILD_ID, KEY, "user-1") not in limiter._buckets
    assert (GUILD_ID, KEY, "user-2") in limiter._buckets


async def test_a_second_limiter_sharing_the_same_transport_sees_live_updates() -> None:
    """Simulates two processes (e.g. a bot process's automod check and a
    web process's dashboard) sharing one Transport + Store -- a rule
    change made through one must be picked up by the other without a
    restart, the same live-update guarantee CommandRegistry gives."""
    transport = InProcessTransport()
    store = MemoryRateLimitStore()
    writer = GuildRateLimiter(transport, store, default_max_calls=1, default_per_seconds=60.0)
    reader = GuildRateLimiter(transport, store, default_max_calls=1, default_per_seconds=60.0)

    # reader warms its cache with the (currently absent) rule
    assert await reader.check(GUILD_ID, KEY) is True
    assert await reader.check(GUILD_ID, KEY) is False

    await writer.set_rule(GUILD_ID, KEY, max_calls=5, per_seconds=60.0)
    await asyncio.sleep(0.05)  # let InProcessTransport's fire-and-forget dispatch run

    assert await reader.check(GUILD_ID, KEY) is True
