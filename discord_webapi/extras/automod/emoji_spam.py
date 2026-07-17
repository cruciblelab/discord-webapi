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
    # A flag is two REGIONAL INDICATOR SYMBOL codepoints forming one glyph
    # (e.g. U+1F1FA U+1F1F8 = one US flag), and a skin-toned emoji is a
    # base codepoint plus one EMOJI MODIFIER FITZPATRICK codepoint (e.g.
    # U+1F44D U+1F3FD = one medium-toned thumbs-up). Matching each
    # constituent codepoint on its own (the previous single-char-class
    # version of this regex) double-counted every flag and every
    # skin-toned emoji as 2 -- three flags or three skin-toned reactions
    # in a message read as 6 for `max_emoji` purposes instead of 3.
    "(?:[\U0001f1e6-\U0001f1ff]{2})"
    "|(?:[\U0001f300-\U0001faff\U00002600-\U000027bf][\U0001f3fb-\U0001f3ff]?)"
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
