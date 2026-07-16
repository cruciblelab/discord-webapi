"""A configurable `on_message` auto-moderation listener: a banned-word
filter and a simple message-rate spam filter. Both are deliberately
in-memory only (like `commands.ratelimit.TokenBucketLimiter`) rather than
backed by a `Store` -- a process restart just resets everyone's window,
which is harmless for a lightweight filtering heuristic. This is *not* a
punishment-escalation system (no bans/kicks/timeouts, no strike count) --
see `builtins.warn` for that; this only ever deletes a message and
optionally posts a short in-channel notice.
"""

from __future__ import annotations

import time
from collections import deque

import discord
from discord.ext import commands

DEFAULT_BANNED_WORD_MESSAGE = "Your message was removed for containing a blocked word."
DEFAULT_SPAM_MESSAGE = "Please slow down -- you're sending messages too quickly."

_PUNCTUATION_STRIP = ".,!?;:\"'()[]{}"


def setup(
    bot: commands.Bot,
    *,
    banned_words: list[str] | None = None,
    banned_word_message: str = DEFAULT_BANNED_WORD_MESSAGE,
    spam_message_threshold: int | None = 5,
    spam_window_seconds: float = 10.0,
    spam_message: str = DEFAULT_SPAM_MESSAGE,
    delete_offending_messages: bool = True,
    notify_in_channel: bool = True,
    ignore_bots: bool = True,
) -> None:
    """Registers an `on_message` listener doing two independent, optional
    checks:

    - **Banned-word filter**: `banned_words` (case-insensitive, whole-word
      match only -- "ass" in the list won't match "class"). Leave `None`/
      empty (the default) to disable it entirely.
    - **Simple spam filter**: more than `spam_message_threshold` messages
      from the same member in the same channel within `spam_window_seconds`
      triggers it. Set `spam_message_threshold=None` to disable it. Purely
      in-memory per-process, per-(guild, channel, member) sliding window.

    Neither check bans/kicks/times out anyone -- offending messages are
    just deleted (`delete_offending_messages`, requires `manage_messages`)
    with an optional short-lived in-channel reply (`notify_in_channel`,
    auto-deletes after 10s) naming what happened, never a DM.
    """
    banned_word_set = {w.lower() for w in (banned_words or [])}
    recent_messages: dict[tuple[int, int, int], deque[float]] = {}

    def _contains_banned_word(content: str) -> bool:
        if not banned_word_set:
            return False
        words = {w.strip(_PUNCTUATION_STRIP).lower() for w in content.split()}
        return not banned_word_set.isdisjoint(words)

    def _is_spamming(message: discord.Message) -> bool:
        if spam_message_threshold is None:
            return False
        assert message.guild is not None
        key = (message.guild.id, message.channel.id, message.author.id)
        now = time.monotonic()
        window = recent_messages.setdefault(key, deque())
        window.append(now)
        while window and now - window[0] > spam_window_seconds:
            window.popleft()
        return len(window) > spam_message_threshold

    @bot.listen("on_message")
    async def _on_message(message: discord.Message) -> None:
        if message.guild is None:
            return
        if ignore_bots and message.author.bot:
            return

        violation: str | None = None
        if _contains_banned_word(message.content):
            violation = banned_word_message
        elif _is_spamming(message):
            violation = spam_message

        if violation is None:
            return

        if delete_offending_messages:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        if notify_in_channel:
            try:
                await message.channel.send(
                    f"{message.author.mention} {violation}", delete_after=10
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
