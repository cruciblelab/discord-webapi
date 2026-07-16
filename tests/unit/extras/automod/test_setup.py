"""Integration test for the automod package's coordinator (`setup()`) --
the individual checks each have their own dedicated test file
(`test_automod_banned_words.py` etc.); this one verifies the wiring:
exemptions, action-taking (delete/notify/log), and the `on_violation`
hook all work together on a real (fake) `on_message` dispatch.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.extras import automod

GUILD_ID = 1
CHANNEL_ID = 2
LOG_CHANNEL_ID = 3


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_message(
    content: str,
    *,
    author_id: int = 1,
    is_bot: bool = False,
    has_manage_messages: bool = False,
    channel_id: int = CHANNEL_ID,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.guild = MagicMock(id=GUILD_ID)
    message.channel = MagicMock(id=channel_id)
    message.channel.send = AsyncMock()
    message.channel.mention = f"#channel-{channel_id}"
    message.author = MagicMock(spec=discord.Member, id=author_id, bot=is_bot)
    message.author.mention = f"<@{author_id}>"
    message.author.guild_permissions = discord.Permissions(manage_messages=has_manage_messages)
    message.author.roles = []
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.delete = AsyncMock()
    return message


async def _fire_on_message(bot: dpy_commands.Bot, message: discord.Message) -> None:
    for listener in bot.extra_events.get("on_message", []):
        await listener(message)


async def test_banned_word_deletes_and_notifies() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"])
    message = _fake_message("this is a badword right here")

    await _fire_on_message(bot, message)

    message.delete.assert_called_once()
    message.channel.send.assert_called_once()
    assert "blocked word" in message.channel.send.call_args.args[0]


async def test_clean_message_is_untouched() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"])
    message = _fake_message("hello, nice weather today")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()
    message.channel.send.assert_not_called()


async def test_bot_messages_are_ignored_by_default() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"])
    message = _fake_message("badword", is_bot=True)

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_dm_messages_are_ignored() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"])
    message = _fake_message("badword")
    message.guild = None

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_moderators_are_exempt_by_default() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"])
    message = _fake_message("badword", has_manage_messages=True)

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_exempt_channel_is_skipped() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"], exempt_channel_ids=[CHANNEL_ID])
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()


async def test_log_channel_receives_a_permanent_entry() -> None:
    bot = _build_bot()
    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.send = AsyncMock()

    automod.setup(bot, banned_words_list=["badword"], log_channel_id=LOG_CHANNEL_ID)
    message = _fake_message("badword")
    message.guild.get_channel = MagicMock(
        side_effect=lambda cid: log_channel if cid == LOG_CHANNEL_ID else None
    )

    await _fire_on_message(bot, message)

    log_channel.send.assert_called_once()


async def test_on_violation_hook_is_awaited_with_the_reason() -> None:
    bot = _build_bot()
    seen: list[tuple[discord.Message, str]] = []

    async def on_violation(message: discord.Message, reason: str) -> None:
        seen.append((message, reason))

    automod.setup(bot, banned_words_list=["badword"], on_violation=on_violation)
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    assert len(seen) == 1
    assert seen[0][0] is message
    assert "blocked word" in seen[0][1]


async def test_delete_can_be_disabled_independent_of_notify() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"], delete_offending_messages=False)
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    message.delete.assert_not_called()
    message.channel.send.assert_called_once()


async def test_notify_can_be_disabled_independent_of_delete() -> None:
    bot = _build_bot()
    automod.setup(bot, banned_words_list=["badword"], notify_in_channel=False)
    message = _fake_message("badword")

    await _fire_on_message(bot, message)

    message.delete.assert_called_once()
    message.channel.send.assert_not_called()


async def test_first_matching_check_wins_and_short_circuits() -> None:
    """mention_spam is checked before link_filter in the configured
    order -- with both violations present, only the first check's
    reason should show up (and only one delete)."""
    bot = _build_bot()
    automod.setup(bot, max_mentions=0, blocked_domains=["evil.com"])
    message = _fake_message("check out https://evil.com")
    message.mention_everyone = True

    await _fire_on_message(bot, message)

    message.delete.assert_called_once()
    assert "mentioned" in message.channel.send.call_args.args[0]
