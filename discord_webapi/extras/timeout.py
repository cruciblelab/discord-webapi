"""A fully-configurable timeout ("mute") command -- same conventions as
`ban.py`/`kick.py`, reusing the shared role-hierarchy check from
`discord_webapi.extras._shared`. Uses Discord's own native timeout
feature (`Member.timeout`), not a custom mute-role implementation --
one less thing for a consumer to have to configure or maintain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

DEFAULT_DURATION_MINUTES = 10
MAX_DURATION_DAYS = 28  # Discord's own timeout ceiling


def setup(
    bot: commands.Bot,
    *,
    command_name: str = "timeout",
    require_reason: bool = True,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
    dm_before_timeout: bool = True,
    audit_logger: AuditLogger | None = None,
) -> Any:
    """Registers a timeout command on `bot` and returns it.

    `duration_minutes` is clamped to Discord's own 28-day ceiling. Pass
    `duration_minutes=0` to remove an existing timeout instead of setting
    one -- mirrors Discord's own `Member.timeout(None)` semantics.

    Same optional heads-up DM as `extras.ban`/`kick` (`dm_before_timeout=
    True`, best-effort, never blocks the timeout) and the same opt-in
    `audit_logger` convention as `extras.warn`.
    """

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=command_name, description="Time out (mute) a member for a duration"
    )
    @app_commands.describe(
        member="The member to time out",
        duration_minutes="How long to mute them for, in minutes (0 clears an existing timeout)",
        reason="Why this member is being timed out",
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(
        ctx: commands.Context[commands.Bot],
        member: discord.Member,
        duration_minutes: int = default_duration_minutes,
        reason: str | None = None,
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required to time out this member.", ephemeral=True)
            return
        if ctx.guild is None:
            return

        hierarchy_error = check_role_hierarchy(ctx, member)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        audit_reason = build_audit_reason(ctx.author, reason)

        if duration_minutes <= 0:
            try:
                await member.timeout(None, reason=audit_reason)
            except discord.Forbidden:
                await ctx.reply(
                    "I don't have permission to clear that member's timeout.", ephemeral=True
                )
                return
            except discord.NotFound:
                await ctx.reply("That member is no longer in the server.", ephemeral=True)
                return
            if audit_logger is not None:
                await audit_logger.record(
                    guild_id=ctx.guild.id,
                    actor_user_id=ctx.author.id,
                    action="timeout.clear",
                    target=str(member.id),
                    detail={"reason": reason},
                )
            await ctx.reply(f"Cleared the timeout on **{member}**.")
            return

        clamped_minutes = min(duration_minutes, MAX_DURATION_DAYS * 24 * 60)
        until = datetime.now(UTC) + timedelta(minutes=clamped_minutes)

        if dm_before_timeout:
            notice = (
                f"You have been timed out in **{ctx.guild.name}** "
                f"for {clamped_minutes} minute(s)."
            )
            if reason:
                notice += f"\nReason: {reason}"
            await notify_member_best_effort(member, notice)

        try:
            await member.timeout(until, reason=audit_reason)
        except discord.Forbidden:
            await ctx.reply("I don't have permission to time out that member.", ephemeral=True)
            return
        except discord.NotFound:
            await ctx.reply("That member is no longer in the server.", ephemeral=True)
            return

        if audit_logger is not None:
            await audit_logger.record(
                guild_id=ctx.guild.id,
                actor_user_id=ctx.author.id,
                action="timeout",
                target=str(member.id),
                detail={"reason": reason, "minutes": clamped_minutes},
            )

        confirmation = f"Timed out **{member}** for {clamped_minutes} minute(s)."
        if reason:
            confirmation += f"\nReason: {reason}"
        await ctx.reply(confirmation)

    return timeout
