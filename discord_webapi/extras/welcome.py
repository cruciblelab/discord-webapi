"""A configurable `on_member_join` welcome-message listener -- the first
non-command builtin, proving the "one file, one `setup()`" convention
extends to Gateway event listeners, not just commands.
"""

from __future__ import annotations

import discord
from discord.ext import commands

DEFAULT_MESSAGE_TEMPLATE = "Welcome {mention} to **{guild}**! We're glad you're here."


def setup(
    bot: commands.Bot,
    *,
    channel_id: int | None = None,
    message_template: str = DEFAULT_MESSAGE_TEMPLATE,
    dm_instead: bool = False,
) -> None:
    """Registers an `on_member_join` listener on `bot`.

    `message_template` is formatted with `mention` (the new member's
    mention string), `member` (their display name), and `guild` (the
    guild's name) -- pass your own template to change the wording
    entirely, there's no fixed copy baked in.

    `channel_id`: which channel to post the welcome message in. If
    `None` (the default) and `dm_instead=False`, this listener does
    nothing -- it never guesses a "general" channel. Set `dm_instead=True`
    to DM the new member directly instead of posting in a channel
    (best-effort; a closed DM is silently skipped, same as the
    moderation builtins' notification helper).
    """

    @bot.listen("on_member_join")
    async def _on_member_join(member: discord.Member) -> None:
        text = message_template.format(
            mention=member.mention, member=member.display_name, guild=member.guild.name
        )

        if dm_instead:
            try:
                await member.send(text)
            except discord.HTTPException:
                pass
            return

        if channel_id is None:
            return
        channel = member.guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(text)
