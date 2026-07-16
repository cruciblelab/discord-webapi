"""A fully-configurable kick command -- same conventions as `ban.py`,
reusing the same shared role-hierarchy check and best-effort DM helper
from `discord_webapi.extras._shared` rather than duplicating them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from discord_webapi.extras._shared import (
    build_audit_reason,
    check_role_hierarchy,
    notify_member_best_effort,
)

if TYPE_CHECKING:
    from discord_webapi.audit.logger import AuditLogger


def setup(
    bot: commands.Bot,
    *,
    command_name: str = "kick",
    require_reason: bool = True,
    dm_before_kick: bool = True,
    audit_logger: AuditLogger | None = None,
) -> Any:
    """Registers a kick command on `bot` and returns it.

    Same role-hierarchy protection as `extras.ban` (refuses if the
    target outranks the bot or the invoking moderator), an optional
    heads-up DM before the kick lands (best-effort, never blocks the
    kick), an optional required reason for Discord's own audit log, and
    an opt-in `audit_logger` (same convention as `extras.warn`).
    """

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=command_name, description="Kick a member from the server"
    )
    @app_commands.describe(
        member="The member to kick", reason="Why this member is being kicked"
    )
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(
        ctx: commands.Context[commands.Bot],
        member: discord.Member,
        reason: str | None = None,
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required to kick this member.", ephemeral=True)
            return
        if ctx.guild is None:
            return

        hierarchy_error = check_role_hierarchy(ctx, member)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        if dm_before_kick:
            notice = f"You have been kicked from **{ctx.guild.name}**."
            if reason:
                notice += f"\nReason: {reason}"
            await notify_member_best_effort(member, notice)

        audit_reason = build_audit_reason(ctx.author, reason)
        try:
            await ctx.guild.kick(member, reason=audit_reason)
        except discord.Forbidden:
            await ctx.reply(
                "I don't have permission to kick that member.", ephemeral=True
            )
            return
        except discord.NotFound:
            await ctx.reply("That member is no longer in the server.", ephemeral=True)
            return

        if audit_logger is not None:
            await audit_logger.record(
                guild_id=ctx.guild.id,
                actor_user_id=ctx.author.id,
                action="kick",
                target=str(member.id),
                detail={"reason": reason},
            )

        confirmation = f"Kicked **{member}**."
        if reason:
            confirmation += f"\nReason: {reason}"
        await ctx.reply(confirmation)

    return kick
