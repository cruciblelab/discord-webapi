from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.extras.kick import setup as setup_kick


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
    ctx.guild.kick = AsyncMock()
    ctx.guild.name = "Test Guild"
    return ctx


def _fake_member(*, top_role: int = 1) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.top_role = top_role
    member.send = AsyncMock()
    return member


def test_setup_registers_a_hybrid_command_named_kick() -> None:
    bot = _build_bot()

    command = setup_kick(bot)

    assert command.name == "kick"
    assert bot.get_command("kick") is command


async def test_reason_required_by_default_blocks_without_one() -> None:
    bot = _build_bot()
    command = setup_kick(bot)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, None)

    ctx.guild.kick.assert_not_called()


async def test_refuses_to_kick_a_member_who_outranks_the_moderator() -> None:
    bot = _build_bot()
    command = setup_kick(bot, dm_before_kick=False)
    ctx = _fake_ctx(author_top_role=1, bot_top_role=100)
    member = _fake_member(top_role=99)

    await command.callback(ctx, member, "spamming")

    ctx.guild.kick.assert_not_called()
    assert "outranks yours" in ctx.reply.call_args.args[0]


async def test_successful_kick_sends_dm_and_confirmation() -> None:
    bot = _build_bot()
    command = setup_kick(bot, dm_before_kick=True)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, "spamming")

    member.send.assert_called_once()
    ctx.guild.kick.assert_called_once()
    ctx.reply.assert_called_once()
