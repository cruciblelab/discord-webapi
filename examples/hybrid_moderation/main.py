"""Focused example: the three moderation systems working together, each
staying in its own lane -- automod *detects*, warn *remembers*, and the
escalation engine *decides the punishment* -- with nothing hardcoded.

The point is that these are independent, composable pieces, not one
monolithic "moderation bot":

  automod (message check) --on_violation--> your glue code, which:
      1. records a warning in a WarnStore (persistent per-user count)
      2. records a violation in the EscalationEngine under key "automod"

  the EscalationEngine then applies whatever rung the *server owner*
  configured for that count (timeout / kick / ban / nothing) -- there are
  NO built-in thresholds, you set them live from the dashboard.

So automod knows nothing about punishment, warn knows nothing about
automod, and the escalation ladder is 100% server-configured. Swap any one
of them for your own implementation without touching the others.

Run:
    pip install -e ".[sql]"                     # from the repo root
    cp examples/hybrid_moderation/.env.example examples/hybrid_moderation/.env
    # fill in .env, then:
    set -a && source examples/hybrid_moderation/.env && set +a
    uvicorn main:app --reload --app-dir examples/hybrid_moderation

Try it:
    1. Configure the ladder (no restart), e.g. timeout at 3 automod hits,
       kick at 5:
         PUT /api/guilds/{gid}/escalation-rules/automod/3
             {"action": "timeout", "action_minutes": 10}
         PUT /api/guilds/{gid}/escalation-rules/automod/5
             {"action": "kick"}
    2. Add a banned word (edit BANNED_WORDS below) and post it -> automod
       deletes it, a warning is recorded, and once the count hits a
       configured rung the escalation engine acts.
    3. `/warns @member` shows the running count; the same count drives both
       the manual /warn command and automod's auto-warns.
"""

from datetime import UTC, datetime

import discord
from discord.ext import commands

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents
from discord_webapi.extras.automod import setup as setup_automod
from discord_webapi.extras.warn import MemoryWarnStore, WarnRecord
from discord_webapi.extras.warn import setup as setup_warn

BANNED_WORDS = ["spamword"]  # add real ones to see automod trigger

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)

# One shared WarnStore backs both the manual /warn command and automod's
# auto-warns, so a member's count is the same however the warning arrived.
# Swap MemoryWarnStore for SQLWarnStore(engine) to persist across restarts.
warn_store = MemoryWarnStore()
setup_warn(bot, store=warn_store)


app = DiscordWebAPI.quickstart(
    bot=bot,
    enable_escalation_api=True,   # PUT /api/guilds/{id}/escalation-rules/{key}/{threshold}
    enable_ratelimits_api=True,
)
escalation = app.state.discord_webapi_escalation_engine


async def on_automod_violation(message: discord.Message, reason: str) -> None:
    """The glue: automod detected something, so remember it (warn) and let
    the server-configured ladder decide what happens (escalation). Neither
    automod nor this callback contains any punishment logic."""
    if message.guild is None or not isinstance(message.author, discord.Member):
        return
    await warn_store.add(
        WarnRecord(
            guild_id=message.guild.id,
            user_id=message.author.id,
            moderator_id=message.guild.me.id,  # the bot itself
            reason=f"automod: {reason}",
            created_at=datetime.now(UTC),
        )
    )
    await escalation.record_violation(
        message.author, "automod", source="automod", reason=reason
    )


setup_automod(
    bot,
    banned_words_list=BANNED_WORDS,
    block_invites=True,
    on_violation=on_automod_violation,
)
