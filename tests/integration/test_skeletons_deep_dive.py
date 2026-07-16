"""Executes the exact scenarios described in
`discord_webapi/skeletons/README.md`'s "Deep dive" section, so those
examples are provably true rather than just prose: dashboard-driven live
rate-limit changes, writing to your own database from inside a
skeleton-wrapped command, opting out of the rate limit entirely,
combining a skeleton with EscalationEngine in one command, and two
guilds behaving independently under the same code.
"""

import tempfile
from pathlib import Path

import aiosqlite
import discord
from discord.ext import commands as dpy_commands

from discord_webapi.escalation import (
    EscalationAction,
    EscalationEngine,
    MemoryEscalationRuleStore,
    MemoryViolationStore,
)
from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.skeletons._shared import rate_limited
from discord_webapi.skeletons.ping import ping
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.transport import InProcessTransport


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


class _FakeCtx:
    def __init__(self, *, guild_id: int, user_id: int) -> None:
        self.guild = discord.Object(id=guild_id)
        self.author = discord.Object(id=user_id)
        self.bot = _build_bot()
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


async def test_dashboard_rule_change_takes_effect_without_touching_the_command() -> None:
    """Scenario 1: PUT-ing a new rule through GuildRateLimiter (what the
    dashboard API's PUT endpoint does under the hood) changes what the
    already-registered command allows, with zero code changes to it."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=5)
    bot = _build_bot()

    calls = []

    @bot.command(name="ping")
    @ping(rate_limiter=limiter)
    async def ping_cmd(ctx: _FakeCtx) -> None:
        calls.append(1)
        await ctx.reply("pong")

    guild_a = _FakeCtx(guild_id=1, user_id=1)
    guild_b = _FakeCtx(guild_id=2, user_id=1)

    # tighten guild 1 to 1 call/60s -- guild 2 keeps the library-wide default
    await limiter.set_rule(1, "ping", max_calls=1, per_seconds=60.0)

    await ping_cmd.callback(guild_a)
    await ping_cmd.callback(guild_a)  # blocked -- guild 1's tightened rule
    await ping_cmd.callback(guild_b)
    await ping_cmd.callback(guild_b)  # still allowed -- guild 2 untouched

    assert guild_a.replies == ["pong", "Slow down! Try again in a moment."]
    assert guild_b.replies == ["pong", "pong"]

    # removing the override reverts guild 1 to the default immediately
    await limiter.delete_rule(1, "ping")
    await ping_cmd.callback(guild_a)
    assert guild_a.replies[-1] == "pong"


async def test_skeleton_wrapped_command_writes_to_its_own_database() -> None:
    """Scenario 2: the skeleton's rate-limit check and the command's own
    persistence are entirely separate -- discord_webapi never sees or
    touches the ping_history table."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=10)
    bot = _build_bot()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ping_history.sqlite3"

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE ping_history (guild_id INTEGER, user_id INTEGER, latency_ms REAL)"
            )
            await db.commit()

        @bot.command(name="ping")
        @ping(rate_limiter=limiter)
        async def ping_cmd(ctx: _FakeCtx) -> None:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO ping_history VALUES (?, ?, ?)",
                    (ctx.guild.id, ctx.author.id, 12.5),
                )
                await db.commit()
            await ctx.reply("pong")

        ctx = _FakeCtx(guild_id=1, user_id=1)
        await ping_cmd.callback(ctx)
        await ping_cmd.callback(ctx)

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM ping_history WHERE guild_id = 1")
            (count,) = await cursor.fetchone()

        assert count == 2
        assert ctx.replies == ["pong", "pong"]


async def test_opting_out_of_the_rate_limit_entirely() -> None:
    """Scenario 3: rate_limiter=None (or skipping the decorator outright)
    means the skeleton does nothing but call your function, unlimited."""
    bot = _build_bot()
    calls = []

    @bot.command(name="ping")
    @ping()  # no rate_limiter passed
    async def ping_cmd(ctx: _FakeCtx) -> None:
        calls.append(1)
        await ctx.reply("pong")

    ctx = _FakeCtx(guild_id=1, user_id=1)
    for _ in range(20):
        await ping_cmd.callback(ctx)

    assert len(calls) == 20
    assert ctx.replies == ["pong"] * 20


async def test_skeleton_combined_with_escalation_engine_in_one_command() -> None:
    """Scenario 4: a command rate-limited by the ping-style decorator
    that also drives EscalationEngine's own independently-configured
    ladder -- two systems, wired together entirely in the handler body."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=10)
    engine = EscalationEngine(transport, MemoryEscalationRuleStore(), MemoryViolationStore())
    await engine.set_rule(1, "reports", 2, action=EscalationAction.KICK)
    bot = _build_bot()

    class _ReportCtx(_FakeCtx):
        def __init__(self, *, guild_id: int, user_id: int, target: object) -> None:
            super().__init__(guild_id=guild_id, user_id=user_id)
            self.target = target
            self.sent: list[str] = []

        async def send(self, content: str) -> None:
            self.sent.append(content)

    class _FakeGuild:
        def __init__(self, guild_id: int) -> None:
            self.id = guild_id
            self.kicked: list[object] = []

        async def kick(self, member: object, *, reason: str | None = None) -> None:
            self.kicked.append(member)

    class _FakeMember:
        def __init__(self, user_id: int, guild_id: int) -> None:
            self.id = user_id
            self.guild = _FakeGuild(guild_id)

    @bot.hybrid_command(name="report")
    @rate_limited("report", rate_limiter=limiter)
    async def report_cmd(ctx: _ReportCtx) -> None:
        outcome = await engine.record_violation(
            ctx.target, "reports", source="user-report", reason="testing"
        )
        await ctx.reply(f"Reported. count={outcome.count}")
        if outcome.triggered_rule is not None:
            await ctx.send("threshold hit")

    member = _FakeMember(user_id=999, guild_id=1)
    ctx1 = _ReportCtx(guild_id=1, user_id=1, target=member)
    ctx2 = _ReportCtx(guild_id=1, user_id=1, target=member)

    await report_cmd.callback(ctx1)
    await report_cmd.callback(ctx2)

    assert ctx1.replies == ["Reported. count=1"]
    assert ctx2.replies == ["Reported. count=2"]
    assert ctx2.sent == ["threshold hit"]
    assert member.guild.kicked == [member]


async def test_two_guilds_stay_fully_independent_under_the_same_command_code() -> None:
    """Scenario 5: the same command code, no guild_id branching anywhere
    in it, behaves differently per guild purely because the store holds
    different rules for each (guild_id, key) pair."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=5)
    bot = _build_bot()

    @bot.command(name="ping")
    @ping(rate_limiter=limiter)
    async def ping_cmd(ctx: _FakeCtx) -> None:
        await ctx.reply("pong")

    await limiter.set_rule(1, "ping", max_calls=1, per_seconds=60.0)
    await limiter.set_rule(2, "ping", max_calls=3, per_seconds=60.0)

    strict_guild = _FakeCtx(guild_id=1, user_id=1)
    loose_guild = _FakeCtx(guild_id=2, user_id=1)

    for _ in range(3):
        await ping_cmd.callback(strict_guild)
    for _ in range(3):
        await ping_cmd.callback(loose_guild)

    assert strict_guild.replies.count("pong") == 1  # only the 1st got through
    assert loose_guild.replies == ["pong", "pong", "pong"]  # all 3 got through
