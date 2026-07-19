"""Executes the exact scenarios described in
`discord_webapi/extras/skeletons/README.md`'s "Deep dive" section, so those
examples are provably true rather than just prose: dashboard-driven live
rate-limit changes, writing to your own database from inside a
skeleton-wrapped command, opting out of the rate limit entirely,
combining a skeleton with EscalationEngine in one command, two guilds
behaving independently under the same code, sharing one handler between a
prefix and slash command, an outer permission check short-circuiting
before the rate limit ever runs, several commands sharing one quota,
and the exact same code running against a SQL-backed store instead of
memory.
"""

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import discord
import pytest_asyncio
from discord.ext import commands as dpy_commands
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.escalation import (
    EscalationAction,
    EscalationEngine,
    MemoryEscalationRuleStore,
    MemoryViolationStore,
)
from discord_webapi.extras.skeletons._shared import rate_limited
from discord_webapi.extras.skeletons.ping import ping
from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.storage.sql import SQLRateLimitStore
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
            self.me = SimpleNamespace(top_role=10)

        async def kick(self, member: object, *, reason: str | None = None) -> None:
            self.kicked.append(member)

    class _FakeMember:
        def __init__(self, user_id: int, guild_id: int) -> None:
            self.id = user_id
            self.guild = _FakeGuild(guild_id)
            self.top_role = 1  # below the bot's (10) -- doesn't outrank it

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


async def test_prefix_and_slash_share_one_handler_and_default_bucket() -> None:
    """Scenario 6: the actual logic lives in one plain function, called
    from both a @bot.command and a @bot.tree.command registration -- and
    since both use the ping skeleton's default rate_limit_key ("ping"),
    they draw from the same per-user bucket."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=1)
    bot = _build_bot()
    sent: list[str] = []

    async def _ping_body(reply) -> None:
        await reply("pong")

    @bot.command(name="ping")
    @ping(rate_limiter=limiter)
    async def ping_cmd(ctx: _FakeCtx) -> None:
        await _ping_body(ctx.reply)

    @bot.command(name="ping-slash-stub")  # stand-in for @bot.tree.command in this test
    @ping(rate_limiter=limiter)
    async def ping_slash(ctx: _FakeCtx) -> None:
        await _ping_body(lambda msg: sent.append(msg))

    ctx = _FakeCtx(guild_id=1, user_id=1)

    await ping_cmd.callback(ctx)  # consumes the shared "ping" bucket's 1 token
    await ping_slash.callback(ctx)  # blocked -- same key, same bucket

    assert ctx.replies == ["pong", "Slow down! Try again in a moment."]
    assert sent == []  # ping_slash's handler body never ran


async def test_outer_permission_check_rejects_before_the_rate_limit_runs() -> None:
    """Scenario 7 (part 1): decorators stack bottom-up -- an outer
    "admin only" check (standing in for discord.py's own
    commands.has_permissions) rejects a non-admin before our rate-limit
    decorator underneath it ever executes. An admin passes the gate and
    is still subject to the rate limit below it -- stacking order
    restricts *who can call the command at all*, not who's exempt from a
    check that runs further in."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=1)
    bot = _build_bot()

    def admin_only(func):
        async def wrapper(ctx: _FakeCtx, *args: object, **kwargs: object) -> None:
            if not getattr(ctx, "is_admin", False):
                ctx.replies.append("Missing permissions.")
                return
            await func(ctx, *args, **kwargs)

        return wrapper

    @bot.command(name="announce")
    @admin_only
    @rate_limited("announce", rate_limiter=limiter)
    async def announce_cmd(ctx: _FakeCtx) -> None:
        await ctx.reply("announced")

    non_admin = _FakeCtx(guild_id=1, user_id=1)
    non_admin.is_admin = False
    admin = _FakeCtx(guild_id=1, user_id=2)
    admin.is_admin = True

    await announce_cmd.callback(non_admin)
    assert non_admin.replies == ["Missing permissions."]
    # the rejected non-admin never touched the rate limiter at all
    assert await limiter.check(1, "announce", sub_key="1") is True

    # the admin passes the gate, but is still bound by the rate limit
    # stacked underneath -- the FIRST call succeeds, the SECOND is blocked
    await announce_cmd.callback(admin)
    await announce_cmd.callback(admin)
    assert admin.replies == ["announced", "Slow down! Try again in a moment."]


async def test_manual_check_lets_admins_bypass_the_rate_limit_entirely() -> None:
    """Scenario 7 (part 2): to actually exempt admins from the rate limit
    itself (not just gate who can call the command), skip decorator
    stacking and call GuildRateLimiter.check(...) conditionally inside
    your own handler instead."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=1)
    bot = _build_bot()

    @bot.command(name="announce")
    async def announce_cmd(ctx: _FakeCtx) -> None:
        if not getattr(ctx, "is_admin", False):
            allowed = await limiter.check(ctx.guild.id, "announce", sub_key=str(ctx.author.id))
            if not allowed:
                await ctx.reply("Slow down!")
                return
        await ctx.reply("announced")

    admin = _FakeCtx(guild_id=1, user_id=2)
    admin.is_admin = True

    # an admin can call it as many times as they like -- the check inside
    # the handler is never even reached for them
    for _ in range(5):
        await announce_cmd.callback(admin)

    assert admin.replies == ["announced"] * 5


async def test_several_commands_share_one_quota_key() -> None:
    """Scenario 8: two different commands passing the same rate_limit_key
    draw from one shared per-user bucket instead of two independent ones."""
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore(), default_max_calls=2)
    bot = _build_bot()

    @bot.command(name="summarize")
    @rate_limited("ai-quota", rate_limiter=limiter)
    async def summarize_cmd(ctx: _FakeCtx) -> None:
        await ctx.reply("summarized")

    @bot.command(name="translate")
    @rate_limited("ai-quota", rate_limiter=limiter)
    async def translate_cmd(ctx: _FakeCtx) -> None:
        await ctx.reply("translated")

    ctx = _FakeCtx(guild_id=1, user_id=1)

    await summarize_cmd.callback(ctx)  # 1st of the shared quota's 2 tokens
    await translate_cmd.callback(ctx)  # 2nd -- still within quota
    await summarize_cmd.callback(ctx)  # 3rd -- blocked, quota exhausted

    assert ctx.replies == ["summarized", "translated", "Slow down! Try again in a moment."]


@pytest_asyncio.fixture
async def sql_engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        yield eng
    finally:
        await eng.dispose()


async def test_same_code_works_identically_against_a_sql_backed_store(
    sql_engine: AsyncEngine,
) -> None:
    """Scenario 10: swapping MemoryRateLimitStore for SQLRateLimitStore
    (what DiscordWebAPI.quickstart() wires up automatically) changes
    nothing about the skeleton, the decorator, or the handler -- only the
    persistence layer underneath GuildRateLimiter."""
    sql_store = SQLRateLimitStore(sql_engine)
    await sql_store.create_all()

    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, sql_store, default_max_calls=5)
    bot = _build_bot()

    @bot.command(name="ping")
    @ping(rate_limiter=limiter)
    async def ping_cmd(ctx: _FakeCtx) -> None:
        await ctx.reply("pong")

    # the exact PUT-equivalent from scenario 1, just backed by SQL now
    await limiter.set_rule(1, "ping", max_calls=1, per_seconds=60.0)

    ctx = _FakeCtx(guild_id=1, user_id=1)
    await ping_cmd.callback(ctx)
    await ping_cmd.callback(ctx)

    assert ctx.replies == ["pong", "Slow down! Try again in a moment."]

    # and the rule really did persist to the SQL store, not just an
    # in-memory cache -- a fresh limiter sharing the same store sees it
    fresh_limiter = GuildRateLimiter(transport, sql_store, default_max_calls=5)
    persisted_rule = await fresh_limiter.get_rule(1, "ping")
    assert persisted_rule is not None
    assert persisted_rule.max_calls == 1
