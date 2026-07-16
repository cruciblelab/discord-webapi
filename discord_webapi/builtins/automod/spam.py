"""Simple message-rate spam filter: more than `threshold` messages from
the same member in the same channel within `window_seconds` gets
flagged. Deliberately in-memory only (no `Store`, no database) -- like
`commands.ratelimit.TokenBucketLimiter`, a process restart resetting
everyone's window is harmless for a heuristic like this, not a
correctness bug.
"""

from __future__ import annotations

import time
from collections import deque

import discord

from discord_webapi.builtins.automod.base import AutomodCheck


def make_check(*, threshold: int | None, window_seconds: float = 10.0) -> AutomodCheck | None:
    """Returns a check flagging a member sending more than `threshold`
    messages (in the same guild+channel) within a `window_seconds`
    sliding window, or `None` if `threshold` is `None` (disabled).
    """
    if threshold is None:
        return None

    recent_messages: dict[tuple[int, int, int], deque[float]] = {}

    def check(message: discord.Message) -> str | None:
        assert message.guild is not None  # automod.setup() already filtered this out
        key = (message.guild.id, message.channel.id, message.author.id)
        now = time.monotonic()
        window = recent_messages.setdefault(key, deque())
        window.append(now)
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) > threshold:
            return "sending messages too quickly"
        return None

    return check
