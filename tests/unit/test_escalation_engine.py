import asyncio
from dataclasses import dataclass, field

from discord_webapi.escalation import EscalationAction, EscalationEngine
from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1
KEY = "warn"


@dataclass
class _FakeGuild:
    id: int = GUILD_ID
    kicked: list[object] = field(default_factory=list)
    banned: list[object] = field(default_factory=list)

    async def kick(self, member: object, *, reason: str | None = None) -> None:
        self.kicked.append((member, reason))

    async def ban(self, member: object, *, reason: str | None = None) -> None:
        self.banned.append((member, reason))


@dataclass
class _FakeMember:
    id: int
    guild: _FakeGuild
    timed_out: list[tuple[object, str | None]] = field(default_factory=list)

    async def timeout(self, until: object, *, reason: str | None = None) -> None:
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
