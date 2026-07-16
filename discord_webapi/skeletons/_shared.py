"""The generic "rebar" every skeleton in this package wraps.

A skeleton is deliberately less than a `discord_webapi.builtins` command:
builtins ship a complete, opinionated implementation (a real reply, a real
DM, a real DB-backed store) you can use as-is. A skeleton is just a
decorator you stack under your own `@bot.command(...)`/
`@bot.tree.command(...)`/`@bot.hybrid_command(...)` -- it does the
infrastructure wiring (here: a dashboard-configurable, per-user rate-limit
check) and then calls your function completely unchanged for everything
the command actually does. This is the same monotonous few lines every
`ping`-shaped command ends up rewriting; the goal is to stop that
repetition, not to hand you a finished command. Entirely optional: skip
this whole package and write the command with plain discord.py (or wire
`GuildRateLimiter`/`EscalationEngine` yourself) if you'd rather not use
this shape at all.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import discord
from discord.ext import commands

from discord_webapi.ratelimits import GuildRateLimiter

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _guild_and_user_id(first_arg: Any) -> tuple[int | None, int]:
    if isinstance(first_arg, discord.Interaction):
        return first_arg.guild_id, first_arg.user.id
    ctx: commands.Context[Any] = first_arg
    return (ctx.guild.id if ctx.guild is not None else None), ctx.author.id


async def _reply_blocked(first_arg: Any, message: str) -> None:
    if isinstance(first_arg, discord.Interaction):
        if first_arg.response.is_done():
            await first_arg.followup.send(message, ephemeral=True)
        else:
            await first_arg.response.send_message(message, ephemeral=True)
    else:
        await first_arg.reply(message)


def rate_limited(
    key: str,
    *,
    rate_limiter: GuildRateLimiter | None = None,
    rate_limited_message: str = "Slow down! Try again in a moment.",
) -> Callable[[F], F]:
    """Stack this under `@bot.command(...)`, `@bot.tree.command(...)`, or
    `@bot.hybrid_command(...)` -- it runs the dashboard-configurable,
    per-user `GuildRateLimiter` check (keyed by `key`,
    `PUT /api/guilds/{guild_id}/ratelimits/{key}`) before ever calling your
    command body. Works with either a classic `commands.Context` or an
    `app_commands`/slash-command `discord.Interaction` as the wrapped
    function's first argument -- whichever discord.py hands it, this
    detects it and replies the right way (`ctx.reply` vs.
    `interaction.response.send_message(..., ephemeral=True)`).

    DMs (no guild) always skip the check -- `GuildRateLimiter` is keyed by
    guild and a DM has none. Pass `rate_limiter=None` (the default) to
    skip rate limiting entirely; the decorator then only ever calls your
    function, unchanged.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(first: Any, *args: Any, **kwargs: Any) -> Any:
            if rate_limiter is not None:
                guild_id, user_id = _guild_and_user_id(first)
                if guild_id is not None:
                    allowed = await rate_limiter.check(guild_id, key, sub_key=str(user_id))
                    if not allowed:
                        await _reply_blocked(first, rate_limited_message)
                        return None
            return await func(first, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
