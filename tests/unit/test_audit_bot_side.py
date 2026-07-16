"""Opt-in audit for bot-side moderation actions (warn / escalation /
automod) -- previously audit only covered web-side dashboard writes.
Each integration is a no-op unless an AuditLogger is explicitly passed."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.audit.logger import AuditLogger
from discord_webapi.escalation import EscalationAction, EscalationEngine
from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.extras.automod import setup as setup_automod
from discord_webapi.extras.warn import MemoryWarnStore
from discord_webapi.extras.warn import setup as setup_warn
from discord_webapi.storage.memory import MemoryAuditStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


# -- escalation --


@dataclass
class _FakeGuild:
    id: int = GUILD_ID
    me: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(id=777))

    async def kick(self, member: object, *, reason: str | None = None) -> None: ...
    async def ban(self, member: object, *, reason: str | None = None) -> None: ...


@dataclass
class _FakeMember:
    id: int
    guild: _FakeGuild = field(default_factory=_FakeGuild)

    async def timeout(self, until: object, *, reason: str | None = None) -> None: ...


async def test_escalation_records_audit_on_trigger() -> None:
    store = MemoryAuditStore()
    engine = EscalationEngine(
        InProcessTransport(),
        MemoryEscalationRuleStore(),
        MemoryViolationStore(),
        audit_logger=AuditLogger(store),
    )
    await engine.set_rule(GUILD_ID, "automod", 1, action=EscalationAction.KICK)
    member = _FakeMember(id=42)

    await engine.record_violation(member, "automod", reason="spam")

    entries = await store.list_entries(GUILD_ID)
    assert len(entries) == 1
    assert entries[0].action == "escalation.kick"
    assert entries[0].target == "42"
    assert entries[0].actor_user_id == 0  # automatic action
    assert entries[0].detail["count"] == 1


async def test_escalation_without_logger_records_nothing() -> None:
    store = MemoryAuditStore()
    engine = EscalationEngine(
        InProcessTransport(), MemoryEscalationRuleStore(), MemoryViolationStore()
    )
    await engine.set_rule(GUILD_ID, "automod", 1, action=EscalationAction.KICK)

    await engine.record_violation(_FakeMember(id=42), "automod")

    assert await store.list_entries(GUILD_ID) == []


async def test_escalation_no_audit_when_no_rung_fires() -> None:
    store = MemoryAuditStore()
    engine = EscalationEngine(
        InProcessTransport(),
        MemoryEscalationRuleStore(),
        MemoryViolationStore(),
        audit_logger=AuditLogger(store),
    )
    # no rule at threshold 1 -> nothing triggers -> nothing audited
    await engine.record_violation(_FakeMember(id=42), "automod")

    assert await store.list_entries(GUILD_ID) == []


# -- warn --


def _warn_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.reply = AsyncMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 99
    ctx.author.top_role = 5
    ctx.guild.id = GUILD_ID
    ctx.guild.me.top_role = 10
    return ctx


def _warn_member() -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = 42
    m.top_role = 1
    m.timeout = AsyncMock()
    return m


async def test_warn_records_audit_when_logger_given() -> None:
    store = MemoryAuditStore()
    command = setup_warn(_build_bot(), store=MemoryWarnStore(), audit_logger=AuditLogger(store))

    await command.callback(_warn_ctx(), _warn_member(), "being rude")

    entries = await store.list_entries(GUILD_ID)
    assert len(entries) == 1
    assert entries[0].action == "warn"
    assert entries[0].actor_user_id == 99  # the moderator
    assert entries[0].target == "42"


async def test_warn_without_logger_records_nothing() -> None:
    store = MemoryAuditStore()
    command = setup_warn(_build_bot(), store=MemoryWarnStore())

    await command.callback(_warn_ctx(), _warn_member(), "being rude")

    assert await store.list_entries(GUILD_ID) == []


# -- automod --


def _automod_message(content: str) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.guild = MagicMock()
    msg.guild.id = GUILD_ID
    msg.author = MagicMock(spec=discord.Member)
    msg.author.id = 42
    msg.author.bot = False
    msg.author.mention = "<@42>"
    msg.author.guild_permissions = discord.Permissions.none()
    msg.author.roles = []
    msg.channel = MagicMock()
    msg.channel.id = 555
    msg.delete = AsyncMock()
    msg.channel.send = AsyncMock()
    return msg


async def test_automod_records_audit_on_violation() -> None:
    store = MemoryAuditStore()
    bot = _build_bot()
    setup_automod(
        bot,
        banned_words_list=["spamword"],
        spam_message_threshold=None,
        max_mentions=None,
        audit_logger=AuditLogger(store),
    )
    listener = bot.extra_events["on_message"][0]

    await listener(_automod_message("this has spamword in it"))

    entries = await store.list_entries(GUILD_ID)
    assert len(entries) == 1
    assert entries[0].action == "automod.violation"
    assert entries[0].actor_user_id == 0
    assert entries[0].target == "42"


async def test_automod_without_logger_records_nothing() -> None:
    store = MemoryAuditStore()
    bot = _build_bot()
    setup_automod(
        bot,
        banned_words_list=["spamword"],
        spam_message_threshold=None,
        max_mentions=None,
    )
    listener = bot.extra_events["on_message"][0]

    await listener(_automod_message("this has spamword in it"))

    assert await store.list_entries(GUILD_ID) == []
