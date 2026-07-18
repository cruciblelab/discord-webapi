"""Flagship builtin: a fully-configurable ban command.

Usage::

    from discord_webapi.extras.ban import setup as setup_ban

    ban_command = setup_ban(bot)
    registry.command_meta(category="moderation")(ban_command)

See `discord_webapi/extras/README.md` for the conventions this file
follows and why it looks the way it does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from discord_webapi.bot.types import AnyBot
from discord_webapi.extras._shared import (
    build_audit_reason,
    check_role_hierarchy,
    notify_member_best_effort,
)

if TYPE_CHECKING:
    from discord_webapi.audit.logger import AuditLogger

DEFAULT_DELETE_MESSAGE_SECONDS = 0
MAX_DELETE_MESSAGE_SECONDS = 7 * 24 * 3600  # Discord's own API ceiling


def setup(
    bot: AnyBot,
    *,
    command_name: str = "ban",
    require_reason: bool = True,
    dm_before_ban: bool = True,
    default_delete_message_seconds: int = DEFAULT_DELETE_MESSAGE_SECONDS,
    audit_logger: AuditLogger | None = None,
) -> Any:
    """Registers a ban command on `bot` and returns it.

    Goes beyond a bare `guild.ban(member)` one-liner in the ways a real
    moderation dashboard actually needs:

    - **Reason required by default** (`require_reason=True`) — Discord's own
      audit log is far more useful with one; set `False` to make it optional.
    - **Role-hierarchy checks on top of Discord's own** — refuses if the
      target outranks the bot, *or* outranks the invoking moderator, even
      though Discord's permission model alone wouldn't necessarily stop it
      at the API level for every client.
    - **Optional heads-up DM** (`dm_before_ban=True`) sent before the ban
      lands. Best-effort only: DMs are frequently closed/blocked, and that
      must never block the ban itself.
    - **Configurable message-deletion window** in seconds (Discord's own
      unit as of the `delete_message_seconds` ban API), clamped to
      Discord's own 7-day ceiling.
    - **`audit_logger`**: opt-in, same convention as `extras.warn` -- pass
      an `AuditLogger` (e.g. `api.audit_logger`, non-None only when
      `enable_audit_log=True`) to record each ban to the audit trail; omit
      it and nothing is audited.
    """

    @bot.hybrid_command(  # type: ignore[arg-type, untyped-decorator]
        name=command_name, description="Ban a member from the server"
    )
    @app_commands.describe(
        member="The member to ban",
        reason="Why this member is being banned (shown in the audit log)",
        delete_message_seconds="How much of their recent message history to delete (0-604800)",
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        ctx: commands.Context[commands.Bot],
        member: discord.Member,
        reason: str | None = None,
        delete_message_seconds: int = default_delete_message_seconds,
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required to ban this member.", ephemeral=True)
            return
        if ctx.guild is None:
            return

        hierarchy_error = check_role_hierarchy(ctx, member)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        delete_message_seconds = max(0, min(delete_message_seconds, MAX_DELETE_MESSAGE_SECONDS))

        if dm_before_ban:
            notice = f"You have been banned from **{ctx.guild.name}**."
            if reason:
                notice += f"\nReason: {reason}"
            await notify_member_best_effort(member, notice)

        audit_reason = build_audit_reason(ctx.author, reason)
        try:
            await ctx.guild.ban(
                member, reason=audit_reason, delete_message_seconds=delete_message_seconds
            )
        except discord.Forbidden:
            await ctx.reply(
                "I don't have permission to ban that member.", ephemeral=True
            )
            return
        except discord.NotFound:
            await ctx.reply("That member is no longer in the server.", ephemeral=True)
            return

        if audit_logger is not None:
            await audit_logger.record(
                guild_id=ctx.guild.id,
                actor_user_id=ctx.author.id,
                action="ban",
                target=str(member.id),
                detail={"reason": reason},
            )

        confirmation = f"Banned **{member}**."
        if reason:
            confirmation += f"\nReason: {reason}"
        await ctx.reply(confirmation)

    return ban
