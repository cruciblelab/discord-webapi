"""Excessive-emoji filter -- counts both custom Discord emoji
(`<:name:id>`/`<a:name:id>`) and standard Unicode emoji, flagging a
message that piles on more than `max_emoji` of either kind combined.
"""

from __future__ import annotations

import re

import discord

from discord_webapi.extras.automod.base import AutomodCheck

_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_UNICODE_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]"
)


def make_check(*, max_emoji: int | None) -> AutomodCheck | None:
    """Returns a check flagging a message containing more than
    `max_emoji` total emoji (custom + Unicode), or `None` if `max_emoji`
    is `None` (disabled).
    """
    if max_emoji is None:
        return None

    def check(message: discord.Message) -> str | None:
        content_without_custom = _CUSTOM_EMOJI_RE.sub("", message.content)
        count = len(_CUSTOM_EMOJI_RE.findall(message.content)) + len(
            _UNICODE_EMOJI_RE.findall(content_without_custom)
        )
        if count > max_emoji:
            return f"too many emoji ({count})"
        return None

    return check
