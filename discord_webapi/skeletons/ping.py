"""The first skeleton: the "rebar" for a ping-shaped command. discord_webapi
registers the command and wires up the per-guild, dashboard-configurable
rate limit; you write what actually happens when it fires (the reply,
latency reporting, whatever else you want on top).

    from discord_webapi.skeletons.ping import ping_skeleton

    async def my_ping(ctx):
        await ctx.reply(f"pong ({ctx.bot.latency * 1000:.0f}ms)")

    ping_skeleton(bot, my_ping, rate_limiter=api.rate_limiter)

If you don't want a rate limit at all, just omit `rate_limiter` -- the
skeleton then only registers the command and calls your handler.
"""

from __future__ import annotations

from typing import Any

from discord.ext import commands

from discord_webapi.ratelimits import GuildRateLimiter
from discord_webapi.skeletons._shared import Handler, rate_limited_command_skeleton


def ping_skeleton(
    bot: commands.Bot,
    handler: Handler,
    *,
    rate_limiter: GuildRateLimiter | None = None,
    command_name: str = "ping",
    description: str = "Replies with pong",
    rate_limit_key: str = "ping",
    rate_limited_message: str = "Slow down! Try again in a moment.",
) -> Any:
    return rate_limited_command_skeleton(
        bot,
        handler,
        command_name=command_name,
        description=description,
        rate_limiter=rate_limiter,
        rate_limit_key=rate_limit_key,
        rate_limited_message=rate_limited_message,
    )
