"""A standalone leaf module (no other `discord_webapi` imports) so every
place that needs `AnyBot` -- including modules `discord_webapi.bot.extension`
itself imports, like `commands.bridge` -- can import it without a circular
import.
"""

from __future__ import annotations

from typing import TypeAlias

from discord.ext import commands

# `commands.Bot` and `commands.AutoShardedBot` are sibling classes (neither
# subclasses the other), but share the exact same `.guilds`/`.get_guild()`/
# `.tree`/`.walk_commands()` surface this library ever touches -- nothing
# here cares how many Gateway shards are behind the bot object, since
# discord.py already merges every shard's cache into one `.guilds`
# collection. Every `bot:` parameter across the library accepts this alias
# instead of the narrower `commands.Bot` so large (sharded) bots don't hit
# a type-checking mismatch for a distinction that doesn't matter at runtime.
AnyBot: TypeAlias = commands.Bot | commands.AutoShardedBot
