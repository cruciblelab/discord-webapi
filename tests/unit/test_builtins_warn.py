from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.builtins.warn import MemoryWarnStore
from discord_webapi.builtins.warn import setup as setup_warn


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_ctx(*, author_top_role: int = 5, bot_top_role: int = 10) -> MagicMock:
    ctx = MagicMock()
    ctx.reply = AsyncMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 1
    ctx.author.top_role = author_top_role
    ctx.guild.id = 999
    ctx.guild.me.top_role = bot_top_role
    return ctx


def _fake_member(*, top_role: int = 1, member_id: int = 42) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.top_role = top_role
    member.timeout = AsyncMock()
    return member


def test_setup_registers_a_hybrid_command_named_warn() -> None:
    bot = _build_bot()

    command = setup_warn(bot)

    assert command.name == "warn"


async def test_memory_store_defaults_and_accumulates_warnings() -> None:
    bot = _build_bot()
    store = MemoryWarnStore()
    command = setup_warn(bot, store=store)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, "spam")
    await command.callback(ctx, member, "spam again")

    warnings = await store.list_for_user(999, 42)
    assert len(warnings) == 2
    assert "(2 total warning(s))" in ctx.reply.call_args.args[0]


async def test_refuses_to_warn_a_member_who_outranks_the_moderator() -> None:
    bot = _build_bot()
    store = MemoryWarnStore()
    command = setup_warn(bot, store=store)
    ctx = _fake_ctx(author_top_role=1, bot_top_role=100)
    member = _fake_member(top_role=99)

    await command.callback(ctx, member, "spam")

    assert await store.list_for_user(999, 42) == []
    assert "outranks yours" in ctx.reply.call_args.args[0]


async def test_auto_timeout_after_threshold() -> None:
    bot = _build_bot()
    store = MemoryWarnStore()
    command = setup_warn(bot, store=store, auto_timeout_after=2, auto_timeout_minutes=5)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, "first")
    member.timeout.assert_not_called()

    await command.callback(ctx, member, "second")
    member.timeout.assert_called_once()
    assert "Auto-timed out" in ctx.reply.call_args.args[0]


async def test_no_auto_timeout_when_not_configured() -> None:
    bot = _build_bot()
    store = MemoryWarnStore()
    command = setup_warn(bot, store=store)
    ctx = _fake_ctx()
    member = _fake_member()

    for _ in range(5):
        await command.callback(ctx, member, "spam")

    member.timeout.assert_not_called()
