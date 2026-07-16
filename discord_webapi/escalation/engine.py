"""`EscalationEngine` -- a generic "N violations -> do this" ladder,
usable from any moderation surface (a hand-written command, `extras.warn`,
`extras.automod`'s `on_violation` hook, ...) instead of each one
inventing its own hardcoded threshold/action.

No thresholds or actions are ever built in. Every rung of every ladder is
something a server owner explicitly configured through the dashboard API
(`build_escalation_router`) or your own code called `set_rule()` for --
an empty ladder for a `(guild_id, key)` just means violations are still
counted, but nothing is ever done about them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import discord

from discord_webapi.escalation.base import EscalationRuleStore, ViolationStore
from discord_webapi.escalation.events import (
    EVENT_TYPE_ESCALATION_RULES_CHANGED,
    EscalationRulesChanged,
)
from discord_webapi.escalation.models import (
    EscalationAction,
    EscalationOutcome,
    EscalationRule,
    ViolationRecord,
)
from discord_webapi.transport.base import Event, Transport


class EscalationEngine:
    """Same live-update architecture as `GuildRateLimiter`/`CommandRegistry`:
    a `Transport` event (`escalation_rules_changed`) invalidates this
    instance's in-memory rule cache the moment any process writes a rule,
    so a dashboard edit takes effect immediately without a restart, in
    every process sharing the same `Transport`/stores.
    """

    def __init__(
        self,
        transport: Transport,
        rule_store: EscalationRuleStore,
        violation_store: ViolationStore,
    ) -> None:
        self.transport = transport
        self.rule_store = rule_store
        self.violation_store = violation_store
        self._rules: dict[tuple[int, str], list[EscalationRule]] = {}
        self._loaded: set[tuple[int, str]] = set()

        transport.subscribe(EVENT_TYPE_ESCALATION_RULES_CHANGED, self._on_rules_changed)

    async def record_violation(
        self,
        member: discord.Member,
        key: str,
        *,
        source: str | None = None,
        reason: str | None = None,
    ) -> EscalationOutcome:
        """Records one violation for `member` under `key`, then checks
        whether the resulting count exactly matches a configured rung --
        if so, applies that rung's action (`timeout`/`kick`/`ban`, or
        does nothing for `none`) and returns what happened.

        Designed around recording violations one at a time (the common
        case: a warn command, an automod hit); if you bulk-adjust a
        member's count some other way, a rung whose threshold gets
        skipped over won't fire retroactively.
        """
        guild_id = member.guild.id
        await self.violation_store.add(
            ViolationRecord(
                guild_id=guild_id,
                user_id=member.id,
                key=key,
                source=source,
                reason=reason,
                created_at=datetime.now(UTC),
            )
        )
        count = await self.violation_store.count(guild_id, member.id, key)

        rules = await self._get_rules(guild_id, key)
        triggered = next((r for r in rules if r.threshold == count), None)
        if triggered is None:
            return EscalationOutcome(count=count, triggered_rule=None)

        await self._apply_action(member, triggered)
        return EscalationOutcome(count=count, triggered_rule=triggered)

    async def get_count(self, guild_id: int, user_id: int, key: str) -> int:
        return await self.violation_store.count(guild_id, user_id, key)

    async def list_rules(self, guild_id: int, key: str) -> list[EscalationRule]:
        return await self._get_rules(guild_id, key)

    async def list_all_rules(self, guild_id: int) -> list[EscalationRule]:
        return await self.rule_store.get_all_rules(guild_id)

    async def set_rule(
        self,
        guild_id: int,
        key: str,
        threshold: int,
        *,
        action: EscalationAction,
        action_minutes: int | None = None,
        reason: str | None = None,
        updated_by_user_id: int | None = None,
    ) -> EscalationRule:
        rule = EscalationRule(
            guild_id=guild_id,
            key=key,
            threshold=threshold,
            action=action,
            action_minutes=action_minutes,
            reason=reason,
            updated_at=datetime.now(UTC),
            updated_by_user_id=updated_by_user_id,
        )
        await self.rule_store.set_rule(rule)
        self._invalidate(guild_id, key)
        await self._publish_changed(guild_id, key)
        return rule

    async def delete_rule(self, guild_id: int, key: str, threshold: int) -> None:
        await self.rule_store.delete_rule(guild_id, key, threshold)
        self._invalidate(guild_id, key)
        await self._publish_changed(guild_id, key)

    async def _apply_action(self, member: discord.Member, rule: EscalationRule) -> None:
        reason = rule.reason or (
            f"Automatic escalation: {rule.threshold} violation(s) for {rule.key!r}"
        )
        if rule.action == EscalationAction.NONE:
            return
        if rule.action == EscalationAction.TIMEOUT:
            minutes = rule.action_minutes or 10
            until = discord.utils.utcnow() + timedelta(minutes=minutes)
            await member.timeout(until, reason=reason)
        elif rule.action == EscalationAction.KICK:
            await member.guild.kick(member, reason=reason)
        elif rule.action == EscalationAction.BAN:
            await member.guild.ban(member, reason=reason)

    async def _get_rules(self, guild_id: int, key: str) -> list[EscalationRule]:
        cache_key = (guild_id, key)
        if cache_key in self._loaded:
            return self._rules.get(cache_key, [])
        rules = await self.rule_store.get_rules(guild_id, key)
        self._rules[cache_key] = rules
        self._loaded.add(cache_key)
        return rules

    def _invalidate(self, guild_id: int, key: str) -> None:
        cache_key = (guild_id, key)
        self._rules.pop(cache_key, None)
        self._loaded.discard(cache_key)

    async def _publish_changed(self, guild_id: int, key: str) -> None:
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_ESCALATION_RULES_CHANGED,
                payload=EscalationRulesChanged(guild_id=guild_id, key=key).model_dump(),
            )
        )

    async def _on_rules_changed(self, event: Event) -> None:
        change = EscalationRulesChanged.model_validate(event.payload)
        self._invalidate(change.guild_id, change.key)
