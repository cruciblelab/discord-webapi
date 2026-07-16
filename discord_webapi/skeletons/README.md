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

## Deep dive: everything you can bolt on around it

The examples above only show the bare minimum. Here's the same command
shape stretched across five real scenarios — dashboard-driven
customization, writing to your own database, skipping us entirely,
combining with `EscalationEngine`, and per-guild independent limits —
to show exactly how far "rebar, you build the walls" goes in practice.

### 1. Changing the rate limit from the dashboard, live, no redeploy

The `ping` skeleton's rate limit isn't a constant baked into your code —
it's whatever `GuildRateLimiter` has cached for `(guild_id, "ping")`, and
that cache invalidates itself the instant someone `PUT`s a new rule,
across every process sharing the same `Transport`/store (bot process and
web process included):

```python
@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter)   # rate_limit_key defaults to "ping"
async def ping_cmd(ctx):
    await ctx.reply("pong")
```

```bash
# server owner (or your own admin panel) tightens it for one rowdy guild:
curl -X PUT https://your-dashboard/api/guilds/123456789/ratelimits/ping \
  -H "Authorization: Bearer <session>" -H "Content-Type: application/json" \
  -d '{"max_calls": 1, "per_seconds": 10}'

# a calmer guild gets a looser one, independently:
curl -X PUT https://your-dashboard/api/guilds/987654321/ratelimits/ping \
  -H "Authorization: Bearer <session>" -H "Content-Type: application/json" \
  -d '{"max_calls": 10, "per_seconds": 10}'

# and to remove the override entirely, back to whatever
# default_rate_limit_max_calls/default_rate_limit_per_seconds you set on
# DiscordWebAPI(...):
curl -X DELETE https://your-dashboard/api/guilds/123456789/ratelimits/ping \
  -H "Authorization: Bearer <session>"
```

Nothing in `ping_cmd` above ever changes. The bot doesn't restart. The
next `/ping` in guild `123456789` picks up the new `1 call / 10s` the
moment the `PUT` commits — that's the whole point of the
Transport-event-invalidation design `GuildRateLimiter` shares with
`CommandRegistry`'s own cooldowns.

### 2. Writing to your own database — the skeleton never sees it

The skeleton's only job is the rate-limit check. Everything past that
line is your function, so bolting on your own persistence (a ping-history
table, analytics, whatever) is just... writing to it, the same as if
discord_webapi didn't exist:

```python
import time
import aiosqlite

from discord_webapi.skeletons.ping import ping

DB_PATH = "ping_history.sqlite3"


async def init_ping_history_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS ping_history (
                guild_id INTEGER, user_id INTEGER,
                latency_ms REAL, created_at REAL
            )"""
        )
        await db.commit()


@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter, rate_limit_key="ping")
async def ping_cmd(ctx):
    latency_ms = round(ctx.bot.latency * 1000, 1)

    # your table, your schema, your query -- discord_webapi never touches it
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ping_history VALUES (?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, latency_ms, time.time()),
        )
        await db.commit()

    await ctx.reply(f"pong ({latency_ms}ms)")


@bot.command(name="ping-stats")
async def ping_stats_cmd(ctx):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*), AVG(latency_ms) FROM ping_history WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        count, avg_latency = await cursor.fetchone()
    await ctx.reply(f"{count} pings recorded, {avg_latency:.1f}ms average")
```

Prefer SQLAlchemy over raw `aiosqlite`? Prefer Postgres, a `Store`
Protocol of your own modeled on `discord_webapi.storage.base`, an
in-memory `list` for a quick prototype? All identical — the skeleton
above has no opinion whatsoever about what happens inside `ping_cmd`
after the rate-limit check passes.

### 3. Not using us at all — the escape hatch always exists

If you don't want the rate limit, don't pass `rate_limiter`, or don't use
the decorator at all:

```python
# opt out of the rate limit, keep the (empty) decorator around:
@bot.command(name="ping")
@ping()   # rate_limiter=None -- does nothing but call your function
async def ping_cmd(ctx):
    await ctx.reply("pong")

# or skip discord_webapi entirely:
@bot.command(name="ping")
async def ping_cmd(ctx):
    await ctx.reply("pong")
```

Both are completely valid. Nothing elsewhere in the library assumes every
command goes through a skeleton.

### 4. Combining with `EscalationEngine` — rate limit *and* a ladder, in one command

A command doesn't have to stop at one discord_webapi system. Here's a
`report` command that's both rate-limited (so one user can't spam
reports) *and* escalates the reported member through your own configured
ladder (`PUT /api/guilds/{id}/escalation-rules/reports/{threshold}`) —
two independent systems, wired together entirely in your own function
body:

```python
from discord_webapi.skeletons._shared import rate_limited

@bot.hybrid_command(name="report")
@rate_limited("report", rate_limiter=api.rate_limiter)
async def report_cmd(ctx, member: discord.Member, *, reason: str):
    outcome = await api.escalation_engine.record_violation(
        member, "reports", source="user-report", reason=reason
    )
    await ctx.reply(f"Reported. This user now has {outcome.count} report(s).")
    if outcome.triggered_rule is not None:
        await ctx.send(
            f"{member.mention} hit the `{outcome.triggered_rule.action}` "
            f"threshold at {outcome.count} reports."
        )
```

`rate_limited("report", ...)` is the same generic decorator `ping` is
built from — nothing stops you from using it directly under any command
name you want, not just `"ping"`.

### 5. Two guilds, two completely independent configurations

Because every check is keyed by `(guild_id, key)`, the exact same command
code behaves differently per server without a single `if guild_id ==
...:` in your code — it's all in the store, set via the dashboard API
calls from scenario 1. One guild can have `ping` capped at `1 call/10s`
and `report` capped at `5 calls/60s` with a 3-report ban threshold; a
different guild can leave both at your library-wide defaults, or turn the
`report` ladder off entirely by never configuring a rule for it (an empty
ladder just counts, does nothing — see `discord_webapi.escalation`'s own
docs for why that's the default, not a `none` rule you'd have to write).

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
