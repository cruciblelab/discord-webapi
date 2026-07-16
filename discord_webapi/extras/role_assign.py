"""Role-assignment commands -- give/remove a single Discord role on a
member, e.g. for moderators to hand out a "muted" or "verified" role
without needing the dashboard or the Discord role-management UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from discord_webapi.extras._shared import build_audit_reason, check_role_assignable

if TYPE_CHECKING:
    from discord_webapi.audit.logger import AuditLogger


def setup(
    bot: commands.Bot,
    *,
    add_command_name: str = "role-add",
    remove_command_name: str = "role-remove",
    require_reason: bool = False,
    audit_logger: AuditLogger | None = None,
) -> tuple[Any, Any]:
    """Registers `/role-add` and `/role-remove` commands and returns both.

    Requires `manage_roles` on both the invoking moderator and the bot
    (Discord's own permission check), *and* refuses if the role being
    granted/removed outranks either of them -- see
    `extras._shared.check_role_assignable` for why Discord's own
    hierarchy enforcement alone isn't enough here (it checks the bot's
    hierarchy, not the invoking human's). Opt-in `audit_logger`, same
    convention as `extras.warn`/`ban`/`kick`/`timeout`.
    """

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=add_command_name, description="Give a member a role"
    )
    @app_commands.describe(
        member="The member to give the role to",
        role="The role to give",
        reason="Why this role is being given",
    )
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_add(
        ctx: commands.Context[commands.Bot],
        member: discord.Member,
        role: discord.Role,
        reason: str | None = None,
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required.", ephemeral=True)
            return

        hierarchy_error = check_role_assignable(ctx, role)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        if role in member.roles:
            await ctx.reply(f"{member} already has **{role.name}**.", ephemeral=True)
            return

        audit_reason = build_audit_reason(ctx.author, reason)
        try:
            await member.add_roles(role, reason=audit_reason)
        except discord.Forbidden:
            await ctx.reply("I don't have permission to manage that role.", ephemeral=True)
            return
        except discord.NotFound:
            await ctx.reply("That member is no longer in the server.", ephemeral=True)
            return

        if audit_logger is not None and ctx.guild is not None:
            await audit_logger.record(
                guild_id=ctx.guild.id,
                actor_user_id=ctx.author.id,
                action="role_assign.add",
                target=str(member.id),
                detail={"role_id": role.id, "reason": reason},
            )

        await ctx.reply(f"Gave **{role.name}** to {member}.")

    @bot.hybrid_command(  # type: ignore[arg-type]
        name=remove_command_name, description="Remove a role from a member"
    )
    @app_commands.describe(
        member="The member to remove the role from",
        role="The role to remove",
        reason="Why this role is being removed",
    )
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_remove(
        ctx: commands.Context[commands.Bot],
        member: discord.Member,
        role: discord.Role,
        reason: str | None = None,
    ) -> None:
        if require_reason and not reason:
            await ctx.reply("A reason is required.", ephemeral=True)
            return

        hierarchy_error = check_role_assignable(ctx, role)
        if hierarchy_error is not None:
            await ctx.reply(hierarchy_error, ephemeral=True)
            return

        if role not in member.roles:
            await ctx.reply(f"{member} doesn't have **{role.name}**.", ephemeral=True)
            return

        audit_reason = build_audit_reason(ctx.author, reason)
        try:
            await member.remove_roles(role, reason=audit_reason)
        except discord.Forbidden:
            await ctx.reply("I don't have permission to manage that role.", ephemeral=True)
            return
        except discord.NotFound:
            await ctx.reply("That member is no longer in the server.", ephemeral=True)
            return

        if audit_logger is not None and ctx.guild is not None:
            await audit_logger.record(
                guild_id=ctx.guild.id,
                actor_user_id=ctx.author.id,
                action="role_assign.remove",
                target=str(member.id),
                detail={"role_id": role.id, "reason": reason},
            )

        await ctx.reply(f"Removed **{role.name}** from {member}.")

    return role_add, role_remove
