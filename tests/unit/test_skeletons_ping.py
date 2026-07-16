from types import SimpleNamespace

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.skeletons.ping import ping_skeleton
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.transport import InProcessTransport


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_ctx(*, guild_id: int | None, user_id: int = 1) -> SimpleNamespace:
    replies: list[tuple[str, bool]] = []

    async def reply(content: str, *, ephemeral: bool = False) -> None:
        replies.append((content, ephemeral))

    return SimpleNamespace(
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        author=SimpleNamespace(id=user_id),
        reply=reply,
        _replies=replies,
    )


async def test_calls_handler_when_no_rate_limiter_given() -> None:
    bot = _build_bot()
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler)
    ctx = _fake_ctx(guild_id=1)

    await command.callback(ctx)

    assert called == [ctx]
    assert ctx._replies == []


async def test_calls_handler_when_rate_limit_allows() -> None:
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=5)
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler, rate_limiter=limiter)
    ctx = _fake_ctx(guild_id=1)

    await command.callback(ctx)

    assert called == [ctx]


async def test_blocks_handler_when_rate_limited() -> None:
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler, rate_limiter=limiter, rate_limited_message="slow down")
    ctx1 = _fake_ctx(guild_id=1)
    ctx2 = _fake_ctx(guild_id=1)

    await command.callback(ctx1)
    await command.callback(ctx2)

    assert called == [ctx1]
    assert ctx2._replies == [("slow down", True)]


async def test_rate_limit_is_per_user_sub_key() -> None:
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler, rate_limiter=limiter)
    ctx_user1 = _fake_ctx(guild_id=1, user_id=1)
    ctx_user2 = _fake_ctx(guild_id=1, user_id=2)

    await command.callback(ctx_user1)
    await command.callback(ctx_user2)

    assert called == [ctx_user1, ctx_user2]


async def test_dm_context_skips_rate_limit_check() -> None:
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler, rate_limiter=limiter)
    ctx1 = _fake_ctx(guild_id=None)
    ctx2 = _fake_ctx(guild_id=None)

    await command.callback(ctx1)
    await command.callback(ctx2)

    assert called == [ctx1, ctx2]


async def test_rate_limit_key_defaults_to_ping_regardless_of_command_name() -> None:
    """`rate_limit_key` defaults to `"ping"` even if `command_name` is
    renamed -- the dashboard-facing key stays stable across a rename
    unless you explicitly pass a different `rate_limit_key`."""
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)

    async def handler(ctx: object) -> None:
        return None

    command = ping_skeleton(bot, handler, rate_limiter=limiter, command_name="pingskel")
    ctx = _fake_ctx(guild_id=1, user_id=1)

    await command.callback(ctx)

    assert await limiter.check(1, "ping", sub_key="1") is False


async def test_custom_rate_limit_key() -> None:
    bot = _build_bot()
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    async def handler(ctx: object) -> None:
        called.append(ctx)

    command = ping_skeleton(bot, handler, rate_limiter=limiter, rate_limit_key="custom.ping")
    ctx = _fake_ctx(guild_id=1)

    await command.callback(ctx)
    await command.callback(ctx)

    assert called == [ctx]
    assert await limiter.check(1, "custom.ping", sub_key="1") is False
