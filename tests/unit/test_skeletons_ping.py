from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.skeletons.ping import ping
from discord_webapi.storage.memory import MemoryRateLimitStore
from discord_webapi.transport import InProcessTransport


def _fake_ctx(*, guild_id: int | None, user_id: int = 1) -> SimpleNamespace:
    replies: list[str] = []

    async def reply(content: str) -> None:
        replies.append(content)

    return SimpleNamespace(
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        author=SimpleNamespace(id=user_id),
        reply=reply,
        _replies=replies,
    )


def _fake_interaction(*, guild_id: int | None, user_id: int = 1) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    interaction.user = SimpleNamespace(id=user_id)
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def test_calls_handler_when_no_rate_limiter_given() -> None:
    called = []

    @ping()
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx = _fake_ctx(guild_id=1)
    await handler(ctx)

    assert called == [ctx]
    assert ctx._replies == []


async def test_calls_handler_when_rate_limit_allows() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=5)
    called = []

    @ping(rate_limiter=limiter)
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx = _fake_ctx(guild_id=1)
    await handler(ctx)

    assert called == [ctx]


async def test_blocks_handler_when_rate_limited_with_context() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter, rate_limited_message="slow down")
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx1 = _fake_ctx(guild_id=1)
    ctx2 = _fake_ctx(guild_id=1)

    await handler(ctx1)
    await handler(ctx2)

    assert called == [ctx1]
    assert ctx2._replies == ["slow down"]


async def test_blocks_handler_when_rate_limited_with_interaction() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter, rate_limited_message="slow down")
    async def handler(interaction: object) -> None:
        called.append(interaction)

    interaction1 = _fake_interaction(guild_id=1)
    interaction2 = _fake_interaction(guild_id=1)

    await handler(interaction1)
    await handler(interaction2)

    assert called == [interaction1]
    interaction2.response.send_message.assert_awaited_once_with("slow down", ephemeral=True)


async def test_interaction_uses_followup_if_already_responded() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)

    @ping(rate_limiter=limiter)
    async def handler(interaction: object) -> None:
        return None

    interaction1 = _fake_interaction(guild_id=1)
    interaction2 = _fake_interaction(guild_id=1)
    interaction2.response.is_done.return_value = True

    await handler(interaction1)
    await handler(interaction2)

    interaction2.followup.send.assert_awaited_once_with(
        "Slow down! Try again in a moment.", ephemeral=True
    )
    interaction2.response.send_message.assert_not_awaited()


async def test_rate_limit_is_per_user_sub_key() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter)
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx_user1 = _fake_ctx(guild_id=1, user_id=1)
    ctx_user2 = _fake_ctx(guild_id=1, user_id=2)

    await handler(ctx_user1)
    await handler(ctx_user2)

    assert called == [ctx_user1, ctx_user2]


async def test_dm_context_skips_rate_limit_check() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter)
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx1 = _fake_ctx(guild_id=None)
    ctx2 = _fake_ctx(guild_id=None)

    await handler(ctx1)
    await handler(ctx2)

    assert called == [ctx1, ctx2]


async def test_dm_interaction_skips_rate_limit_check() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter)
    async def handler(interaction: object) -> None:
        called.append(interaction)

    interaction1 = _fake_interaction(guild_id=None)
    interaction2 = _fake_interaction(guild_id=None)

    await handler(interaction1)
    await handler(interaction2)

    assert called == [interaction1, interaction2]


async def test_rate_limit_key_defaults_to_ping() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)

    @ping(rate_limiter=limiter)
    async def handler(ctx: object) -> None:
        return None

    ctx = _fake_ctx(guild_id=1, user_id=1)
    await handler(ctx)

    assert await limiter.check(1, "ping", sub_key="1") is False


async def test_custom_rate_limit_key() -> None:
    limiter = GuildRateLimiter(InProcessTransport(), MemoryRateLimitStore(), default_max_calls=1)
    called = []

    @ping(rate_limiter=limiter, rate_limit_key="custom.ping")
    async def handler(ctx: object) -> None:
        called.append(ctx)

    ctx = _fake_ctx(guild_id=1, user_id=1)

    await handler(ctx)
    await handler(ctx)

    assert called == [ctx]
    assert await limiter.check(1, "custom.ping", sub_key="1") is False
