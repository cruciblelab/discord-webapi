"""A fully-configurable timeout ("mute") command -- same conventions as
`ban.py`/`kick.py`, reusing the shared role-hierarchy check from
`discord_webapi.extras._shared`. Uses Discord's own native timeout
feature (`Member.timeout`), not a custom mute-role implementation --
one less thing for a consumer to have to configure or maintain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from discord_webapi.extras._shared import check_role_hierarchy

DEFAULT_DURATION_MINUTES = 10
MAX_DURATION_DAYS = 28  # Discord's own timeout ceiling


def setup(
    bot: commands.Bot,
    *,
    command_name: str = "timeout",
    require_reason: bool = True,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> Any:
    """Registers a timeout command on `bot` and returns it.

    `duration_minutes` is clamped to Discord's own 28-day ceiling. Pass
    `duration_minutes=0` to remove an existing timeout instead of setting
    one -- mirrors Discord's own `Member.timeout(None)` semantics.
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

        audit_reason = f"{ctx.author} (via discord-webapi): {reason}" if reason else str(ctx.author)

        if duration_minutes <= 0:
            await member.timeout(None, reason=audit_reason)
            await ctx.reply(f"Cleared the timeout on **{member}**.")
            return

        clamped_minutes = min(duration_minutes, MAX_DURATION_DAYS * 24 * 60)
        until = datetime.now(UTC) + timedelta(minutes=clamped_minutes)
        await member.timeout(until, reason=audit_reason)

        confirmation = f"Timed out **{member}** for {clamped_minutes} minute(s)."
        if reason:
            confirmation += f"\nReason: {reason}"
        await ctx.reply(confirmation)

    return timeout
