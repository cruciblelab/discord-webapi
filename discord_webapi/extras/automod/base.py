"""The shared shape every automod check speaks -- deliberately tiny so
each check module (`banned_words.py`, `spam.py`, `mention_spam.py`, ...)
is independently usable, testable, and importable on its own, exactly the
same "use the whole builtin, use one piece, or write your own" philosophy
`_shared.py` already follows for the moderation-command builtins.

A check is a plain, synchronous function -- no `await`, no I/O, no
database. Every check only ever looks at data already on the
`discord.Message` object the Gateway handed the bot, the same
no-extra-fetch principle the rest of this library follows (see
`authz/cache.py`, `commands/bridge.py`). That keeps every check trivially
fast and trivially unit-testable with a plain fake message object -- no
event loop, no mocked HTTP calls, nothing async to await.
"""

from __future__ import annotations

from collections.abc import Callable

import discord

AutomodCheck = Callable[[discord.Message], "str | None"]
"""A check inspects a message and returns a short, user-facing violation
reason (e.g. "contains a blocked word") if it should be flagged, or
`None` if the message is fine. Returning a reason does not itself do
anything -- `automod.setup()` is the only thing that acts on it (deletes
the message, notifies, logs), so a check is pure and side-effect-free."""
