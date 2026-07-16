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

### 6. One handler shared between the prefix and slash version — no duplicated logic

The decorator works on plain `async def` functions, so nothing stops you
from writing the actual logic once and registering it twice:

```python
async def _ping_body(reply) -> None:
    await reply("pong")

@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_cmd(ctx):
    await _ping_body(ctx.reply)

@bot.tree.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_slash(interaction: discord.Interaction):
    await _ping_body(lambda msg: interaction.response.send_message(msg))
```

Both get their own independent rate-limit bucket by default
(`rate_limit_key="ping"` for both, since it's the same skeleton call) —
pass a different `rate_limit_key` to one of them if you want the prefix
and slash versions to count separately instead of sharing one bucket.

### 7. Restricting a command to admins, with our rate limit still underneath

The skeleton doesn't know anything about roles or permissions — that
check is exactly the kind of thing you write yourself, stacked around
ours. Decorators apply bottom-up, so whichever one you put *outermost*
runs *first* and can reject the call before anything below it (including
our rate-limit check) ever executes:

```python
@bot.command(name="announce")
@dpy_commands.has_permissions(administrator=True)  # outermost -- runs first
@rate_limited("announce", rate_limiter=api.rate_limiter)
async def announce_cmd(ctx, *, message: str):
    await ctx.send(message)
```

A non-admin is rejected by `has_permissions` before our decorator ever
sees the call. An admin passes the permission gate and is *still* subject
to the `"announce"` rate limit underneath — stacking order restricts
*who can call the command at all*, it doesn't exempt anyone from a check
that runs further in.

If you actually want admins **exempt from the rate limit itself** (not
just allowed to call the command), that's a conditional inside your own
handler rather than decorator stacking — skip the decorator and call
`GuildRateLimiter.check(...)` yourself:

```python
@bot.command(name="announce")
async def announce_cmd(ctx, *, message: str):
    is_admin = ctx.author.guild_permissions.administrator
    if not is_admin:
        allowed = await api.rate_limiter.check(
            ctx.guild.id, "announce", sub_key=str(ctx.author.id)
        )
        if not allowed:
            await ctx.reply("Slow down!", ephemeral=True)
            return
    await ctx.send(message)
```

### 8. Several different commands sharing one daily quota

`rate_limit_key` doesn't have to match the command name — pass the same
key to several different skeleton-wrapped commands and they all draw
from one shared bucket, e.g. a combined "AI-backed commands" daily quota
instead of a separate limit per command:

```python
@bot.command(name="summarize")
@rate_limited("ai-quota", rate_limiter=api.rate_limiter)
async def summarize_cmd(ctx, *, text: str):
    await ctx.reply(call_llm(f"Summarize: {text}"))

@bot.command(name="translate")
@rate_limited("ai-quota", rate_limiter=api.rate_limiter)
async def translate_cmd(ctx, *, text: str):
    await ctx.reply(call_llm(f"Translate: {text}"))
```

Configure the shared quota once:
`PUT /api/guilds/{id}/ratelimits/ai-quota {"max_calls": 20, "per_seconds": 86400}`
— 20 calls per day total across *both* commands, per user, per guild.

### 9. Customizing (or localizing) the rate-limited reply

`rate_limited_message` is just a string you pass in — nothing stops you
from picking it per-guild, per-locale, or generating it dynamically by
wrapping the decorator call in your own small helper:

```python
GUILD_LOCALES = {123456789: "tr", 987654321: "en"}

MESSAGES = {
    "tr": "Yavaş ol! Biraz sonra tekrar dene.",
    "en": "Slow down! Try again in a moment.",
}

def localized_ping(guild_id: int):
    locale = GUILD_LOCALES.get(guild_id, "en")
    return ping(rate_limiter=api.rate_limiter, rate_limited_message=MESSAGES[locale])

# picking the decorator per-guild means registering per-guild commands,
# which is unusual for a single global bot -- the more common shape is a
# single rate_limited_message that itself looks the locale up:

async def _localized_message(ctx) -> str:
    return MESSAGES.get(GUILD_LOCALES.get(ctx.guild.id), MESSAGES["en"])
```

In practice, if you need real per-invocation dynamic messages (not just a
static string), it's simplest to skip the decorator's built-in reply and
call `GuildRateLimiter.check(...)` yourself inside the handler — see
`examples/full_featured_bot/main.py`'s hand-written `/ping` for exactly
that shape.

### 10. Backed by Postgres/MySQL instead of memory — the same code, in production

Every example above works identically whether `api.rate_limiter` is
backed by `MemoryRateLimitStore` (what `DiscordWebAPI()` uses if you
don't pass a store) or `SQLRateLimitStore` (what `DiscordWebAPI.quickstart()`
wires up automatically) — the skeleton, the decorator, your handler, none
of it changes:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from discord_webapi import DiscordWebAPI
from discord_webapi.storage.sql import SQLRateLimitStore

engine = create_async_engine("postgresql+asyncpg://user:pass@host/db")
api = DiscordWebAPI(
    bot=bot,
    transport=transport,
    auth=auth,
    rate_limit_store=SQLRateLimitStore(engine),  # only line that changed
)

@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter)  # identical to every example above
async def ping_cmd(ctx):
    await ctx.reply("pong")
```

Every `PUT /api/guilds/{id}/ratelimits/{key}` from scenario 1 now
persists to Postgres and survives a restart, instead of resetting with
an in-memory store — nothing about the command or the decorator needed
to know that.

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
