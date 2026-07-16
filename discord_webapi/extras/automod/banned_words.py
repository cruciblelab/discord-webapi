"""Banned-word filter -- case-insensitive, whole-word matching only, so
`banned_words=["ass"]` doesn't flag "class". Independently usable: import
just `make_check` if you're composing your own message listener instead
of using `automod.setup()`.
"""

from __future__ import annotations

import discord

from discord_webapi.extras.automod.base import AutomodCheck

_PUNCTUATION_STRIP = ".,!?;:\"'()[]{}"


def make_check(words: list[str]) -> AutomodCheck | None:
    """Returns a check flagging any message containing one of `words` as
    a whole word (case-insensitive), or `None` if `words` is empty --
    `automod.setup()` treats a `None` return as "this check is disabled",
    so an empty list cleanly turns the whole filter off rather than
    running a no-op check on every message.
    """
    banned = {w.lower() for w in words}
    if not banned:
        return None

    def check(message: discord.Message) -> str | None:
        message_words = {w.strip(_PUNCTUATION_STRIP).lower() for w in message.content.split()}
        if banned.isdisjoint(message_words):
            return None
        return "contains a blocked word"

    return check
