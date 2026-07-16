"""Mass-mention filter -- flags a message that mentions more members/
roles than `max_mentions`, the classic raid/troll pattern of pinging
everyone at once. Counts `@everyone`/`@here` as a single mention each,
same weight as pinging one member.
"""

from __future__ import annotations

import discord

from discord_webapi.builtins.automod.base import AutomodCheck


def make_check(*, max_mentions: int | None) -> AutomodCheck | None:
    """Returns a check flagging a message with more than `max_mentions`
    total user/role/@everyone mentions, or `None` if `max_mentions` is
    `None` (disabled).
    """
    if max_mentions is None:
        return None

    def check(message: discord.Message) -> str | None:
        total = len(message.mentions) + len(message.role_mentions)
        if message.mention_everyone:
            total += 1
        if total > max_mentions:
            return f"mentioned too many users/roles at once ({total})"
        return None

    return check
