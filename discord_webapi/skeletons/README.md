# `discord_webapi.skeletons`

Rebar, not a finished building. `discord_webapi.builtins` ships a
complete, opinionated command (a real reply, a real DM, a real store) you
can use as-is. A skeleton ships only the **infrastructure wiring** — the
registered command, the dashboard-configurable per-guild rate-limit check
— and calls your own handler for everything the command actually *does*.
This is the direction the library is leaning going forward: focus effort
on the Discord-facing systems/algorithms (rate limiting, escalation
ladders, permission checks, ...) and let skeletons be the thin, optional
glue between "discord.py command" and "our infrastructure," instead of
growing an ever-larger catalog of fully-baked commands. `builtins` isn't
going away — it's just no longer where new effort defaults to; a new
skeleton (or a new system like `escalation`/`ratelimits`) is preferred
over a new full builtin unless a real gap in the infrastructure itself
shows up first.

## Convention

- **One file per command shape**, same as `builtins` — no auto-discovery,
  nothing runs until you import it and call it.
- **You always write the handler.** A skeleton never decides what a
  command replies with, DMs, or does beyond the infrastructure check —
  that's the whole point of "rebar, not a finished wall."
- **Every piece of infrastructure is optional.** Pass `rate_limiter=None`
  (the default) and a skeleton just registers the command and calls your
  handler — no forced dependency on any discord_webapi system.
- **Fully skippable.** Nothing stops you from writing the same command in
  plain discord.py, or wiring `GuildRateLimiter`/`EscalationEngine`
  yourself the way `examples/full_featured_bot/main.py`'s hand-written
  `/ping` command already does — skeletons exist for people who'd rather
  not repeat that wiring by hand every time.

## Example

```python
from discord_webapi.skeletons.ping import ping_skeleton

async def my_ping(ctx):
    await ctx.reply(f"pong ({ctx.bot.latency * 1000:.0f}ms)")

ping_skeleton(bot, my_ping, rate_limiter=api.rate_limiter)
```

Dashboard-configurable per-guild, same as any `GuildRateLimiter` key:

```
PUT /api/guilds/{guild_id}/ratelimits/ping
{"max_calls": 1, "per_seconds": 3}
```

## What's here so far

- `_shared.py::rate_limited_command_skeleton` — the generic factory every
  skeleton in this package is built from: registers a hybrid command,
  optionally checks a `GuildRateLimiter` keyed per-user
  (`sub_key=str(ctx.author.id)`) before calling your handler, skips the
  check entirely in DMs (no guild to key by) or when no rate limiter is
  given.
- `ping.py::ping_skeleton` — the first concrete skeleton, a thin wrapper
  around `rate_limited_command_skeleton` with ping-shaped defaults
  (`command_name="ping"`, `rate_limit_key="ping"`).

More skeletons (and more infrastructure systems to hang them off of) are
expected to follow the same shape: a thin, named wrapper around shared
"rebar" factories, never a finished command.
