from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.builtins.automod import setup as setup_automod

GUILD_ID = 1
CHANNEL_ID = 2


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_message(content: str, *, author_id: int = 1, is_bot: bool = False) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.guild = MagicMock(id=GUILD_ID)
    message.channel = MagicMock(id=CHANNEL_ID)
    message.channel.send = AsyncMock()
    message.author = MagicMock(id=author_id, bot=is_bot)
    message.delete = AsyncMock()
    return message


async def _fire_on_message(bot: dpy_commands.Bot, message: discord.Message) -> None:
    for listener in bot.extra_events.get("on_message", []):
        await listener(message)


async def test_banned_word_triggers_deletion_and_notice() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"])
    message = _fake_message("this has a badword in it")

    await _fire_on_message(bot, message)

    message.delete.assert_called_once()
    message.channel.send.assert_called_once()


async def test_banned_word_is_whole_word_only() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["ass"])
    message = _fake_message("i am writing about the word class here")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_clean_message_is_left_alone() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"])
    message = _fake_message("hello, how is everyone doing today?")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()
    message.channel.send.assert_not_called()


async def test_dm_messages_are_ignored() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"])
    message = _fake_message("badword")
    message.guild = None

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_bot_messages_are_ignored_by_default() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"])
    message = _fake_message("badword", is_bot=True)

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_spam_filter_triggers_after_threshold_within_window() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=[], spam_message_threshold=2, spam_window_seconds=60.0)

    for _ in range(3):
        message = _fake_message("hi")
        await _fire_on_message(bot, message)

    # Only the message that pushed the count over the threshold gets deleted.
    message.delete.assert_called_once()


async def test_spam_filter_disabled_when_threshold_is_none() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=[], spam_message_threshold=None)

    for _ in range(20):
        message = _fake_message("hi")
        await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_delete_offending_messages_can_be_disabled() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"], delete_offending_messages=False)
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()
    message.channel.send.assert_called_once()


async def test_notify_in_channel_can_be_disabled() -> None:
    bot = _build_bot()
    setup_automod(bot, banned_words=["badword"], notify_in_channel=False)
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    message.delete.assert_called_once()
    message.channel.send.assert_not_called()
