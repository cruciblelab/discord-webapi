"""Focused example: writing your OWN command from scratch, using
discord-webapi only for the repetitive infrastructure (a per-guild,
dashboard-configurable rate limit) via a skeleton decorator.

This is the "rebar, not a finished wall" use case (see
`discord_webapi/extras/skeletons/README.md`): discord-webapi doesn't
decide what your `/weather` command *says* -- you write that -- it just
wires the rate-limit check so you don't rewrite that boilerplate for every
command. The rate limit is configurable per server, live, from the
dashboard, keyed by whatever string you choose ("weather" here).

Run:
    pip install -e ".[sql]"                     # from the repo root
    cp examples/skeleton_custom_command/.env.example examples/skeleton_custom_command/.env
    # fill in .env, then:
    set -a && source examples/skeleton_custom_command/.env && set +a
    uvicorn main:app --reload --app-dir examples/skeleton_custom_command

Try it:
    1. `/weather Istanbul` in Discord -> your own reply.
    2. Configure the rate limit for one guild, live, no restart:
       PUT /api/guilds/{guild_id}/ratelimits/weather
           {"max_calls": 1, "per_seconds": 30}
    3. Spam `/weather` -> after the first call in 30s you get the
       rate-limited reply, per user, only in that guild.
"""

from discord.ext import commands

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents
from discord_webapi.extras.skeletons import rate_limited

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)


# Your command body -- discord-webapi never touches what's inside. Swap in a
# real weather API call; this demo just echoes so it needs no API key.
async def weather(ctx: commands.Context, city: str) -> None:
    await ctx.reply(f"The weather in {city} is a balmy 22C. (demo)")


# quickstart() builds the whole web/auth/storage side and returns the app;
# the rate limiter it constructs lives at app.state.discord_webapi_ratelimiter.
app = DiscordWebAPI.quickstart(
    bot=bot,
    enable_ratelimits_api=True,  # exposes PUT /api/guilds/{id}/ratelimits/{key}
)
limiter = app.state.discord_webapi_ratelimiter

# Register the command *after* the app exists, so the skeleton decorator
# gets the real limiter. `rate_limited("weather", ...)` is the rebar; the
# `weather` function above is the wall you built. (If you construct your
# DiscordWebAPI before defining commands -- the composable API rather than
# quickstart -- you'd just stack `@rate_limited("weather",
# rate_limiter=api.rate_limiter)` under `@bot.hybrid_command(...)` inline.)
bot.hybrid_command(name="weather", description="Look up the weather (demo)")(
    rate_limited("weather", rate_limiter=limiter)(weather)
)
