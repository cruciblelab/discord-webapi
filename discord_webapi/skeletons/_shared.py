"""The generic "rebar" every skeleton in this package is built from.

A skeleton is deliberately less than a `discord_webapi.builtins` command:
builtins ship a complete, opinionated implementation (a real reply, a real
DM, a real DB-backed store) you can use as-is. A skeleton ships only the
*infrastructure wiring* -- command registration, the dashboard-configurable
per-guild rate-limit check -- and calls your own `handler(ctx)` for
everything the command actually does. Nothing here is a finished command;
think of it as the rebar poured before you decide what the building looks
like. Entirely optional: skip this whole package and write the command
with plain discord.py (plus, if you want them, `GuildRateLimiter`/
`EscalationEngine` directly) if you'd rather not use this shape at all.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from discord.ext import commands

from discord_webapi.ratelimits import GuildRateLimiter

Handler = Callable[[commands.Context[commands.Bot]], Awaitable[None]]


def rate_limited_command_skeleton(
    bot: commands.Bot,
    handler: Handler,
    *,
    command_name: str,
    description: str,
    rate_limiter: GuildRateLimiter | None = None,
    rate_limit_key: str | None = None,
    rate_limited_message: str = "Slow down! Try again in a moment.",
) -> Any:
    """Registers `command_name` as a hybrid command that, if `rate_limiter`
    is given, checks it (keyed by `rate_limit_key`, per-user via
    `sub_key=str(ctx.author.id)`, per-guild-configurable at
    `PUT /api/guilds/{guild_id}/ratelimits/{rate_limit_key}`) before ever
    calling your `handler`. Pass `rate_limiter=None` (the default) to skip
    rate limiting entirely -- the skeleton then does nothing but register
    the command and call `handler`.

    DM invocations (`ctx.guild is None`) always skip the rate-limit check,
    same reasoning as the rest of the library: `GuildRateLimiter` is keyed
    by guild, and a DM has none.
    """
    key = rate_limit_key or command_name

    @bot.hybrid_command(name=command_name, description=description)
    async def _command(ctx: commands.Context[commands.Bot]) -> None:
        if rate_limiter is not None and ctx.guild is not None:
            allowed = await rate_limiter.check(ctx.guild.id, key, sub_key=str(ctx.author.id))
            if not allowed:
                await ctx.reply(rate_limited_message, ephemeral=True)
                return
        await handler(ctx)

    return _command
