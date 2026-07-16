"""Small, independently-usable primitives shared by builtins in this
package -- role-hierarchy checks, best-effort DM delivery.

These are exported and documented on their own precisely so a consumer can
take *one* piece (say, just the hierarchy check) into a command they wrote
completely from scratch, without having to adopt an entire builtin
command wholesale. Nothing here is private glue -- see
`discord_webapi/extras/README.md` for the "use it whole, in pieces, or
not at all" philosophy this package follows.

This module deliberately stays free of any database/cache dependency --
it only ever touches the `discord.Member`/`discord.Guild` objects already
in the bot's warm Gateway cache, the same no-extra-fetch principle the
rest of this library follows (see `authz/cache.py`). If a future builtin
needs its own persistent state (e.g. `warn.py` tracking a warning count),
that gets its own `Store` protocol + Memory/SQL pair, following the exact
same pattern as `AuditStore`/`ConsentStore` -- not bolted onto this file.
"""

from __future__ import annotations

import discord
from discord.ext import commands


def check_role_hierarchy(
    ctx: commands.Context[commands.Bot], member: discord.Member
) -> str | None:
    """Returns a user-facing error string if `member` outranks the bot or
    the invoking moderator, else `None`. Shared by every moderation
    builtin (ban, kick, timeout, ...) that acts on another member --
    Discord's own permission model doesn't stop a lower-ranked moderator
    or under-permissioned bot from attempting the action at the API
    level, so this check has to happen on the caller's side.
    """
    me = ctx.guild.me if ctx.guild is not None else None
    if me is not None and member.top_role >= me.top_role:
        return "I can't do that -- their highest role outranks mine (or matches it)."
    if isinstance(ctx.author, discord.Member) and member.top_role >= ctx.author.top_role:
        if member.id == ctx.author.id:
            return "You can't do that to yourself -- your own role can't outrank (or match) itself."
        return "You can't do that -- their highest role outranks yours (or matches it)."
    return None


async def notify_member_best_effort(member: discord.Member, message: str) -> None:
    """Sends `member` a DM, swallowing the near-universal "DMs are closed
    or the bot is blocked" failure. Never raises -- a notification is a
    courtesy, never a precondition for the moderation action itself."""
    try:
        await member.send(message)
    except discord.Forbidden:
        pass
    except discord.HTTPException:
        pass


def check_role_assignable(
    ctx: commands.Context[commands.Bot], role: discord.Role
) -> str | None:
    """Returns a user-facing error string if `role` is at or above the
    bot's or the invoking moderator's own highest role, else `None`.

    Unlike `check_role_hierarchy` (which checks a target *member's* rank),
    this checks the *role being granted/removed* itself. Discord enforces
    role-hierarchy for `MANAGE_ROLES` against whichever identity actually
    calls the API -- since a bot token makes the call, Discord checks the
    **bot's** hierarchy, not the invoking human's, so a role-assignment
    command needs this same client-side guard for the same reason
    `check_role_hierarchy` exists for ban/kick/timeout.
    """
    me = ctx.guild.me if ctx.guild is not None else None
    if me is not None and role >= me.top_role:
        return "I can't manage that role -- it outranks (or matches) my highest role."
    if isinstance(ctx.author, discord.Member) and role >= ctx.author.top_role:
        return "You can't manage that role -- it outranks (or matches) your highest role."
    return None
