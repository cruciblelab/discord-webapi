"""Excessive-caps ("SHOUTING") filter. Only looks at alphabetic
characters (so a message full of numbers/punctuation/emoji can't trip
it), and ignores short messages entirely (`min_length`) since "OK" or
"NO" being all-caps is not shouting.
"""

from __future__ import annotations

import discord

from discord_webapi.extras.automod.base import AutomodCheck


def make_check(*, ratio: float | None, min_length: int = 10) -> AutomodCheck | None:
    """Returns a check flagging a message whose alphabetic characters are
    at least `ratio` (0.0-1.0) uppercase, or `None` if `ratio` is `None`
    (disabled). Messages with fewer than `min_length` letters are never
    flagged, regardless of `ratio`.
    """
    if ratio is None:
        return None

    def check(message: discord.Message) -> str | None:
        letters = [c for c in message.content if c.isalpha()]
        if len(letters) < min_length:
            return None
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= ratio:
            return "excessive caps"
        return None

    return check
