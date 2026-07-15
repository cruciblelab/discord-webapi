from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.builtins.timeout import setup as setup_timeout


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_ctx(*, author_top_role: int = 5, bot_top_role: int = 10) -> MagicMock:
    ctx = MagicMock()
    ctx.reply = AsyncMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.top_role = author_top_role
    ctx.guild.me.top_role = bot_top_role
    ctx.guild.name = "Test Guild"
    return ctx


def _fake_member(*, top_role: int = 1) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.top_role = top_role
    member.timeout = AsyncMock()
    return member


def test_setup_registers_a_hybrid_command_named_timeout() -> None:
    bot = _build_bot()

    command = setup_timeout(bot)

    assert command.name == "timeout"


async def test_default_duration_is_used_when_omitted() -> None:
    bot = _build_bot()
    command = setup_timeout(bot, default_duration_minutes=10)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, 10, "spamming")

    member.timeout.assert_called_once()
    (until,), _kwargs = member.timeout.call_args
    assert until is not None


async def test_duration_is_clamped_to_28_days() -> None:
    bot = _build_bot()
    command = setup_timeout(bot)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, 999_999, "spamming")

    (until,), _kwargs = member.timeout.call_args
    assert until - discord.utils.utcnow() <= timedelta(days=28, minutes=1)


async def test_zero_duration_clears_an_existing_timeout() -> None:
    bot = _build_bot()
    command = setup_timeout(bot, require_reason=False)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, 0, None)

    member.timeout.assert_called_once_with(None, reason=str(ctx.author))


async def test_refuses_to_timeout_a_member_who_outranks_the_moderator() -> None:
    bot = _build_bot()
    command = setup_timeout(bot)
    ctx = _fake_ctx(author_top_role=1, bot_top_role=100)
    member = _fake_member(top_role=99)

    await command.callback(ctx, member, 10, "spamming")

    member.timeout.assert_not_called()
    assert "outranks yours" in ctx.reply.call_args.args[0]
