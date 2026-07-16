"""Exercises discord_webapi.extras.ban directly -- it's public API meant
to be imported and used standalone, so it gets the same test rigor as any
other library surface, not "just an example."
"""

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.extras.ban import setup as setup_ban


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
    ctx.guild.ban = AsyncMock()
    ctx.guild.name = "Test Guild"
    return ctx


def _fake_member(*, top_role: int = 1) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.top_role = top_role
    member.send = AsyncMock()
    member.__str__.return_value = "baduser#0001"
    return member


def test_setup_registers_a_hybrid_command_named_ban() -> None:
    bot = _build_bot()

    command = setup_ban(bot)

    assert command.name == "ban"
    assert bot.get_command("ban") is command


def test_setup_supports_a_custom_command_name() -> None:
    bot = _build_bot()

    command = setup_ban(bot, command_name="yeet")

    assert command.name == "yeet"


async def test_reason_required_by_default_blocks_without_one() -> None:
    bot = _build_bot()
    command = setup_ban(bot)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, None, 0)

    ctx.guild.ban.assert_not_called()
    ctx.reply.assert_called_once()
    assert "reason is required" in ctx.reply.call_args.args[0]


async def test_require_reason_false_allows_banning_without_one() -> None:
    bot = _build_bot()
    command = setup_ban(bot, require_reason=False, dm_before_ban=False)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, None, 0)

    ctx.guild.ban.assert_called_once()


async def test_refuses_to_ban_a_member_who_outranks_the_bot() -> None:
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx(bot_top_role=1)
    member = _fake_member(top_role=99)

    await command.callback(ctx, member, "spamming", 0)

    ctx.guild.ban.assert_not_called()
    assert "outranks mine" in ctx.reply.call_args.args[0]


async def test_refuses_to_ban_a_member_who_outranks_the_moderator() -> None:
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx(author_top_role=1, bot_top_role=100)
    member = _fake_member(top_role=99)

    await command.callback(ctx, member, "spamming", 0)

    ctx.guild.ban.assert_not_called()
    assert "outranks yours" in ctx.reply.call_args.args[0]


async def test_dm_before_ban_is_best_effort_and_never_blocks_the_ban() -> None:
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=True)
    ctx = _fake_ctx()
    member = _fake_member()
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), "blocked")

    await command.callback(ctx, member, "spamming", 0)

    member.send.assert_called_once()
    ctx.guild.ban.assert_called_once()


async def test_delete_message_seconds_is_clamped_to_discords_ceiling() -> None:
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, "spamming", 999_999_999)

    _, kwargs = ctx.guild.ban.call_args
    assert kwargs["delete_message_seconds"] == 7 * 24 * 3600


async def test_forbidden_from_discord_replies_cleanly_instead_of_crashing() -> None:
    """The bot can lack ban_members in practice even though the decorator
    checked at invocation time (permission revoked mid-session, guild-level
    quirks) -- Discord's own 403 must not propagate as an unhandled crash."""
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx()
    member = _fake_member()
    ctx.guild.ban.side_effect = discord.Forbidden(MagicMock(status=403), "missing permissions")

    await command.callback(ctx, member, "spamming", 0)

    assert "permission" in ctx.reply.call_args.args[0].lower()


async def test_not_found_from_discord_replies_cleanly_instead_of_crashing() -> None:
    """The target can leave the server between the hierarchy check and the
    API call -- Discord's own 404 must not propagate as an unhandled crash."""
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx()
    member = _fake_member()
    ctx.guild.ban.side_effect = discord.NotFound(MagicMock(status=404), "unknown member")

    await command.callback(ctx, member, "spamming", 0)

    assert "no longer in the server" in ctx.reply.call_args.args[0].lower()


async def test_audit_logger_records_the_ban_when_configured() -> None:
    bot = _build_bot()
    audit_logger = MagicMock()
    audit_logger.record = AsyncMock()
    command = setup_ban(bot, dm_before_ban=False, audit_logger=audit_logger)
    ctx = _fake_ctx()
    member = _fake_member()
    member.id = 12345

    await command.callback(ctx, member, "spamming", 0)

    audit_logger.record.assert_called_once()
    _, kwargs = audit_logger.record.call_args
    assert kwargs["action"] == "ban"
    assert kwargs["target"] == "12345"
    assert kwargs["detail"]["reason"] == "spamming"


async def test_no_audit_logger_means_no_audit_call() -> None:
    """Opt-in, same as extras.warn -- omitting audit_logger must not crash
    and must not silently create one."""
    bot = _build_bot()
    command = setup_ban(bot, dm_before_ban=False)
    ctx = _fake_ctx()
    member = _fake_member()

    await command.callback(ctx, member, "spamming", 0)

    ctx.guild.ban.assert_called_once()
