# `discord_webapi.skeletons`

Rebar, not a finished building. `discord_webapi.builtins` ships a
complete, opinionated command (a real reply, a real DM, a real store) you
can use as-is. A skeleton is a **decorator you stack under your own
command decorator** (`@bot.command(...)`, `@bot.tree.command(...)`, or
`@bot.hybrid_command(...)`) — it wires up the infrastructure (here: a
dashboard-configurable per-guild rate-limit check) and calls your
function completely unchanged for everything the command actually
*does*. This is the direction the library is leaning going forward: focus
effort on the Discord-facing systems/algorithms (rate limiting,
escalation ladders, permission checks, ...) instead of growing an
ever-larger catalog of fully-baked commands. `builtins` isn't going away —
it's just no longer where new effort defaults to; a new skeleton (or a
new system like `escalation`/`ratelimits`) is preferred over a new full
builtin unless a real gap in the infrastructure itself shows up first.

## Convention

- **One module per command shape**, same as `builtins` — no
  auto-discovery, nothing runs until you import it and use it.
- **A skeleton is a decorator, not a registration function.** You still
  write the actual `@bot.command(...)`/`@bot.tree.command(...)`/
  `@bot.hybrid_command(...)` yourself — the skeleton just stacks under it.
- **You always write the handler body.** A skeleton never decides what a
  command replies with, DMs, or does beyond the infrastructure check —
  that's the whole point of "rebar, not a finished wall."
- **Works with both classic commands and slash commands, unchanged.** The
  decorator inspects its first argument at call time (`commands.Context`
  vs. `discord.Interaction`) and knows how to reply the right way either
  way — the same skeleton works whether you register with
  `@bot.command`/`@bot.hybrid_command` (gets a `Context`) or
  `@bot.tree.command` (gets an `Interaction`).
- **Every piece of infrastructure is optional.** Pass `rate_limiter=None`
  (the default) and a skeleton does nothing but call your function — no
  forced dependency on any discord_webapi system.
- **Fully skippable.** Nothing stops you from writing the same command in
  plain discord.py, or wiring `GuildRateLimiter`/`EscalationEngine`
  yourself the way `examples/full_featured_bot/main.py`'s hand-written
  `/ping` command already does — skeletons exist for people who'd rather
  not repeat that wiring by hand every time.

## Example

Classic prefix command:

```python
from discord_webapi.skeletons.ping import ping

@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_cmd(ctx):
    await ctx.reply("pong")
```

Slash command — same decorator, same import, works with
`discord.Interaction` too:

```python
@bot.tree.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("pong")
```

Dashboard-configurable per-guild, same as any `GuildRateLimiter` key:

```
PUT /api/guilds/{guild_id}/ratelimits/ping
{"max_calls": 1, "per_seconds": 3}
```

## What's here so far

- `_shared.py::rate_limited(key, *, rate_limiter=None, ...)` — the
  generic decorator every skeleton in this package is built from: runs a
  `GuildRateLimiter` check keyed per-user (`sub_key=str(user.id)`) before
  calling your function, skips the check entirely in DMs (no guild to key
  by) or when no rate limiter is given, and replies with the standard
  discord.py mechanism for whichever object it was handed
  (`ctx.reply(...)` vs. `interaction.response.send_message(...,
  ephemeral=True)` / `interaction.followup.send(...)` if the interaction
  already responded).
- `ping.py::ping(*, rate_limiter=None, rate_limit_key="ping", ...)` — the
  first concrete skeleton, a thin wrapper around `rate_limited` with
  ping-shaped defaults.

More skeletons (and more infrastructure systems to hang them off of) are
expected to follow the same shape: a thin, named decorator wrapping
shared "rebar" factories, never a finished command.
