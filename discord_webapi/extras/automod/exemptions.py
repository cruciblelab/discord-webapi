"""Who automod should never touch, regardless of what a check flags --
moderators policing their own server shouldn't get their own messages
deleted by the filter they configured. Independent of any individual
check, applied once up front by `automod.setup()` before running any of
them.
"""

from __future__ import annotations

import discord


def is_exempt(
    message: discord.Message,
    *,
    exempt_role_ids: set[int],
    exempt_channel_ids: set[int],
    bypass_if_manage_messages: bool,
) -> bool:
    """`bypass_if_manage_messages` (default on in `automod.setup()`) trusts
    Discord's own permission model: anyone who can already manually
    delete messages in this channel is trusted not to need the filter
    applied to themselves. `exempt_channel_ids`/`exempt_role_ids` cover
    channels/roles that should never be filtered at all (e.g. a
    staff-only or bot-command channel).
    """
    if message.channel.id in exempt_channel_ids:
        return True

    author = message.author
    if bypass_if_manage_messages and isinstance(author, discord.Member):
        if author.guild_permissions.manage_messages:
            return True

    if exempt_role_ids and isinstance(author, discord.Member):
        author_role_ids = {role.id for role in author.roles}
        if author_role_ids & exempt_role_ids:
            return True

    return False
