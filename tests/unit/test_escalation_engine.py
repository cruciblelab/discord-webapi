import asyncio
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import discord

from discord_webapi.escalation import EscalationAction, EscalationEngine
from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1
KEY = "warn"


@dataclass
class _FakeRole:
    position: int

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, _FakeRole):
            return NotImplemented
        return self.position >= other.position


@dataclass
class _FakeBotMember:
    top_role: _FakeRole = field(default_factory=lambda: _FakeRole(10))


@dataclass
class _FakeGuild:
    id: int = GUILD_ID
    me: _FakeBotMember = field(default_factory=_FakeBotMember)
    kicked: list[object] = field(default_factory=list)
    banned: list[object] = field(default_factory=list)
    kick_error: BaseException | None = None
    ban_error: BaseException | None = None

    async def kick(self, member: object, *, reason: str | None = None) -> None:
        if self.kick_error is not None:
            raise self.kick_error
        self.kicked.append((member, reason))

    async def ban(self, member: object, *, reason: str | None = None) -> None:
        if self.ban_error is not None:
            raise self.ban_error
        self.banned.append((member, reason))


@dataclass
class _FakeMember:
    id: int
    guild: _FakeGuild
    top_role: _FakeRole = field(default_factory=lambda: _FakeRole(1))
    timed_out: list[tuple[object, str | None]] = field(default_factory=list)
    timeout_error: BaseException | None = None

    async def timeout(self, until: object, *, reason: str | None = None) -> None:
        if self.timeout_error is not None:
            raise self.timeout_error
        self.timed_out.append((until, reason))


def _make_engine(**kwargs: object) -> EscalationEngine:
    return EscalationEngine(
        InProcessTransport(), MemoryEscalationRuleStore(), MemoryViolationStore(), **kwargs  # type: ignore[arg-type]
    )


def _make_member(user_id: int = 100) -> _FakeMember:
    guild = _FakeGuild()
    return _FakeMember(id=user_id, guild=guild)


async def test_record_violation_counts_but_does_nothing_with_no_rules() -> None:
    engine = _make_engine()
    member = _make_member()

    outcome = await engine.record_violation(member, KEY)

    assert outcome.count == 1
    assert outcome.triggered_rule is None
    assert member.timed_out == []


async def test_record_violation_triggers_rule_at_exact_threshold() -> None:
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 2, action=EscalationAction.TIMEOUT, action_minutes=5)

    outcome1 = await engine.record_violation(member, KEY)
    assert outcome1.triggered_rule is None
    assert member.timed_out == []

    outcome2 = await engine.record_violation(member, KEY)
    assert outcome2.triggered_rule is not None
    assert outcome2.triggered_rule.action == EscalationAction.TIMEOUT
    assert len(member.timed_out) == 1


async def test_none_action_does_nothing() -> None:
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.NONE)

    outcome = await engine.record_violation(member, KEY)

    assert outcome.triggered_rule is not None
    assert member.timed_out == []
    assert member.guild.kicked == []
    assert member.guild.banned == []


async def test_kick_action_calls_guild_kick() -> None:
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.KICK)

    await engine.record_violation(member, KEY)

    assert len(member.guild.kicked) == 1
    assert member.guild.kicked[0][0] is member


async def test_ban_action_calls_guild_ban() -> None:
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.BAN)

    await engine.record_violation(member, KEY)

    assert len(member.guild.banned) == 1
    assert member.guild.banned[0][0] is member


async def test_apply_action_skips_when_member_outranks_the_bot() -> None:
    """Unlike extras.ban/kick/timeout (which have a human moderator to
    reply an error to), an auto-triggered escalation has no one to hand an
    exception to -- outranking the bot must be logged and skipped, not
    raised (which would crash whatever loop called record_violation(),
    e.g. automod's on_message handler)."""
    engine = _make_engine()
    member = _make_member()
    member.top_role = _FakeRole(position=99)  # outranks the bot's top_role (10)
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.KICK)

    outcome = await engine.record_violation(member, KEY)

    assert outcome.triggered_rule is not None  # the rung still fired...
    assert member.guild.kicked == []  # ...but the kick itself was skipped


async def test_apply_action_handles_forbidden_without_crashing() -> None:
    """A Discord API error (e.g. the member holds Administrator, which
    Discord blocks regardless of role position) must be logged and
    swallowed, not propagate out of record_violation()."""
    engine = _make_engine()
    member = _make_member()
    member.guild.kick_error = discord.Forbidden(MagicMock(status=403), "missing permissions")
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.KICK)

    outcome = await engine.record_violation(member, KEY)

    assert outcome.triggered_rule is not None
    assert member.guild.kicked == []


async def test_skipping_past_a_threshold_does_not_retroactively_fire() -> None:
    """Bulk-adding violations some other way (not via record_violation)
    can skip over a rung -- record_violation only checks the count that
    results from the single violation it just recorded."""
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 3, action=EscalationAction.BAN)

    await engine.record_violation(member, KEY)
    await engine.record_violation(member, KEY)
    await engine.record_violation(member, KEY)

    assert len(member.guild.banned) == 1


async def test_different_users_have_independent_counts() -> None:
    engine = _make_engine()
    member1 = _make_member(user_id=100)
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.KICK)

    await engine.record_violation(member1, KEY)

    assert len(member1.guild.kicked) == 1
    assert await engine.get_count(GUILD_ID, 200, KEY) == 0


async def test_different_keys_have_independent_counts() -> None:
    engine = _make_engine()
    member = _make_member()

    await engine.record_violation(member, "warn")
    await engine.record_violation(member, "automod.spam")

    assert await engine.get_count(GUILD_ID, member.id, "warn") == 1
    assert await engine.get_count(GUILD_ID, member.id, "automod.spam") == 1


async def test_delete_rule_removes_it() -> None:
    engine = _make_engine()
    member = _make_member()
    await engine.set_rule(GUILD_ID, KEY, 1, action=EscalationAction.KICK)

    await engine.delete_rule(GUILD_ID, KEY, 1)
    await engine.record_violation(member, KEY)

    assert member.guild.kicked == []


async def test_list_rules_and_list_all_rules() -> None:
    engine = _make_engine()
    await engine.set_rule(GUILD_ID, "warn", 1, action=EscalationAction.TIMEOUT)
    await engine.set_rule(GUILD_ID, "automod.spam", 1, action=EscalationAction.KICK)

    warn_rules = await engine.list_rules(GUILD_ID, "warn")
    all_rules = await engine.list_all_rules(GUILD_ID)

    assert len(warn_rules) == 1
    assert {r.key for r in all_rules} == {"warn", "automod.spam"}


async def test_a_second_engine_sharing_the_same_transport_sees_live_updates() -> None:
    """Same live-update guarantee as GuildRateLimiter/CommandRegistry: a
    rule change made through one process's engine is picked up by
    another process's engine sharing the same Transport + stores."""
    transport = InProcessTransport()
    rule_store = MemoryEscalationRuleStore()
    violation_store = MemoryViolationStore()
    writer = EscalationEngine(transport, rule_store, violation_store)
    reader = EscalationEngine(transport, rule_store, violation_store)
    member = _make_member()

    # reader warms its cache with the (currently absent) rule
    outcome = await reader.record_violation(member, KEY)
    assert outcome.triggered_rule is None

    await writer.set_rule(GUILD_ID, KEY, 2, action=EscalationAction.KICK)
    await asyncio.sleep(0.05)  # let InProcessTransport's fire-and-forget dispatch run

    outcome2 = await reader.record_violation(member, KEY)
    assert outcome2.triggered_rule is not None
    assert len(member.guild.kicked) == 1
