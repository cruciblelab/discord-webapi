from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.extras.welcome import setup as setup_welcome


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _get_listener(bot: dpy_commands.Bot) -> AsyncMock:
    return bot.extra_events["on_member_join"][0]


def _fake_member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.mention = "<@42>"
    member.display_name = "newbie"
    member.send = AsyncMock()
    member.guild.name = "Test Guild"
    member.guild.get_channel = MagicMock()
    return member


def test_setup_registers_an_on_member_join_listener() -> None:
    bot = _build_bot()

    setup_welcome(bot, channel_id=123)

    assert "on_member_join" in bot.extra_events
    assert len(bot.extra_events["on_member_join"]) == 1


async def test_does_nothing_without_channel_id_or_dm_instead() -> None:
    bot = _build_bot()
    setup_welcome(bot)
    member = _fake_member()

    await _get_listener(bot)(member)

    member.guild.get_channel.assert_not_called()
    member.send.assert_not_called()


async def test_posts_to_the_configured_channel() -> None:
    bot = _build_bot()
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    setup_welcome(bot, channel_id=123)
    member = _fake_member()
    member.guild.get_channel.return_value = channel

    await _get_listener(bot)(member)

    channel.send.assert_called_once()
    assert "Test Guild" in channel.send.call_args.args[0]
    assert "<@42>" in channel.send.call_args.args[0]


async def test_dm_instead_sends_a_dm_and_skips_channel_lookup() -> None:
    bot = _build_bot()
    setup_welcome(bot, dm_instead=True)
    member = _fake_member()

    await _get_listener(bot)(member)

    member.send.assert_called_once()
    member.guild.get_channel.assert_not_called()


async def test_dm_instead_swallows_forbidden() -> None:
    bot = _build_bot()
    setup_welcome(bot, dm_instead=True)
    member = _fake_member()
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), "blocked")

    await _get_listener(bot)(member)  # must not raise


async def test_custom_message_template() -> None:
    bot = _build_bot()
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    setup_welcome(bot, channel_id=123, message_template="Yo {member}, welcome to {guild}!")
    member = _fake_member()
    member.guild.get_channel.return_value = channel

    await _get_listener(bot)(member)

    channel.send.assert_called_once_with("Yo newbie, welcome to Test Guild!")
