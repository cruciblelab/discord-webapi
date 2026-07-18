"""A configurable `on_member_join` welcome-message listener -- the first
non-command builtin, proving the "one file, one `setup()`" convention
extends to Gateway event listeners, not just commands.
"""

from __future__ import annotations

import discord

from discord_webapi.bot.types import AnyBot

DEFAULT_MESSAGE_TEMPLATE = "Welcome {mention} to **{guild}**! We're glad you're here."


def setup(
    bot: AnyBot,
    *,
    channel_id: int | None = None,
    message_template: str = DEFAULT_MESSAGE_TEMPLATE,
    dm_instead: bool = False,
) -> None:
    """Registers an `on_member_join` listener on `bot`.

    `message_template` is formatted with exactly three names -- `mention`
    (the new member's mention string), `member` (their display name), and
    `guild` (the guild's name); any other placeholder in your template
    (e.g. `{user}`) raises `KeyError` inside the listener the moment
    someone joins, since `str.format` has no fallback for an unknown name.

    `channel_id`: which channel to post the welcome message in. If
    `None` (the default) and `dm_instead=False`, this listener does
    nothing -- it never guesses a "general" channel. Set `dm_instead=True`
    to DM the new member directly instead of posting in a channel. Both
    delivery paths are best-effort: a closed DM, or the bot lacking
    permission to post in `channel_id`, is silently skipped rather than
    raising out of the listener (same reasoning as the moderation
    builtins' notification helper -- a failed welcome message shouldn't
    look like a broken bot in your error logs).
    """

    @bot.listen("on_member_join")
    async def _on_member_join(member: discord.Member) -> None:
        try:
            text = message_template.format(
                mention=member.mention, member=member.display_name, guild=member.guild.name
            )
        except (KeyError, IndexError):
            return

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
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass
