"""The first skeleton: the "rebar" for a ping-shaped command. Stack
`ping()` under your own `@bot.command(...)`, `@bot.tree.command(...)`, or
`@bot.hybrid_command(...)` -- discord_webapi wires up the per-guild,
dashboard-configurable rate limit; you write what actually happens when
it fires (the reply, latency reporting, whatever else you want).

Classic prefix command:

    from discord_webapi.extras.skeletons.ping import ping

    @bot.command(name="ping")
    @ping(rate_limiter=api.rate_limiter)
    async def ping_cmd(ctx):
        await ctx.reply("pong")

Slash command -- same decorator, works with `discord.Interaction` too:

    @bot.tree.command(name="ping")
    @ping(rate_limiter=api.rate_limiter)
    async def ping_slash(interaction: discord.Interaction):
        await interaction.response.send_message("pong")

If you don't want a rate limit at all, just omit `rate_limiter` -- the
decorator then does nothing but call your function.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from discord_webapi.extras.skeletons._shared import rate_limited
from discord_webapi.ratelimits import GuildRateLimiter


def ping(
    *,
    rate_limiter: GuildRateLimiter | None = None,
    rate_limit_key: str = "ping",
    rate_limited_message: str = "Slow down! Try again in a moment.",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    return rate_limited(
        rate_limit_key,
        rate_limiter=rate_limiter,
        rate_limited_message=rate_limited_message,
    )
