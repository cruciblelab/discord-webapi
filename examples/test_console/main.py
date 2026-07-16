"""A dedicated physical-test bot + a one-page clickable test console
(`/console`) so every discord-webapi feature can be exercised by clicking
buttons instead of typing curl commands by hand.

Commands on the bot:
    /ping               -- rate-limited via the skeleton decorator (key "ping")
    /warn @member reason -- extras.warn, audited
    /warnings @member    -- lists a tagged member's warning history
    automod (on_message) -- deletes messages containing badword1/2/3,
                             blocks invite links, records a warning AND an
                             escalation violation (key "automod") per hit

Systems wired and testable from the console:
    - command enable/disable + cooldown + required_app_role (live, no restart)
    - GuildRateLimiter (dashboard-configurable "ping" rate limit)
    - EscalationEngine (dashboard-configurable "automod" punishment ladder)
    - AuditLogger (dashboard writes + automod/escalation actions, one trail)
    - warnings listing (a small custom endpoint, not part of the library --
      extras.warn ships storage + a command, not a dashboard API, so this
      is exactly the kind of thing you're expected to write yourself)

Run:
    pip install -e ".[sql]"                       # from the repo root
    cp examples/test_console/.env.example examples/test_console/.env
    # fill in .env, then:
    set -a && source examples/test_console/.env && set +a
    uvicorn main:app --reload --app-dir examples/test_console

Then open http://localhost:8000/console in a browser (or your phone, if
DASHBOARD_BASE_URL points at a reachable address) and click through
TESTING.md's checklist instead of using curl for every step.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord.ext import commands
from fastapi import Depends
from fastapi.responses import FileResponse

from discord_webapi import DiscordWebAPI
from discord_webapi.authz import GuildContext, require_guild_permission
from discord_webapi.bot import default_intents
from discord_webapi.extras.automod import setup as setup_automod
from discord_webapi.extras.skeletons import rate_limited
from discord_webapi.extras.warn import MemoryWarnStore, WarnRecord
from discord_webapi.extras.warn import setup as setup_warn

BANNED_WORDS = ["badword1", "badword2", "badword3"]

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """discord.py's own default: with no error handler at all, a prefix
    command's error (bad syntax, a check failure that raises instead of
    just returning False, ...) is printed to the server's own console and
    NEVER reaches Discord -- from inside Discord it looks exactly like the
    bot silently ignored you. This is what makes that visible for testing
    (a real bot would want friendlier per-error-type messages, but "show
    something" beats "show nothing" for a test console)."""
    await ctx.reply(f"Error: {error}")


# One shared store: the manual /warn command, automod's auto-warns, and the
# /warnings + console listing all read/write the exact same counts.
warn_store = MemoryWarnStore()


async def _ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")


@bot.hybrid_command(name="warnings", description="List a member's warnings")
async def warnings_cmd(ctx: commands.Context, member: discord.Member) -> None:
    if ctx.guild is None:
        return
    records = await warn_store.list_for_user(ctx.guild.id, member.id)
    if not records:
        await ctx.reply(f"{member.mention} has no warnings.")
        return
    lines = [
        f"{i}. {r.created_at:%Y-%m-%d %H:%M} -- {r.reason} (by <@{r.moderator_id}>)"
        for i, r in enumerate(records, start=1)
    ]
    await ctx.reply(f"**{member}** has {len(records)} warning(s):\n" + "\n".join(lines))


# mobile_redirect_uri points straight at the console: after Discord login
# it lands on /console?session_id=...&expires_at=..., and the page's own
# JS reads that out of the URL and stores it -- one click, no copy-pasting
# a token by hand.
_base_url = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")

# quickstart() builds the whole web/auth/storage side; the objects it
# constructs (rate limiter, escalation engine, audit logger) only exist
# once this call returns, so the pieces that need them are wired after it.
app = DiscordWebAPI.quickstart(
    bot=bot,
    mobile_redirect_uri=f"{_base_url}/console",
    enable_ratelimits_api=True,
    enable_escalation_api=True,
    enable_audit_log=True,
)
limiter = app.state.discord_webapi_ratelimiter
escalation = app.state.discord_webapi_escalation_engine
audit_logger = app.state.discord_webapi_audit_logger  # non-None: enable_audit_log=True above

# /ping, rate-limited (key "ping") -- see examples/skeleton_custom_command
# for why this is registered imperatively rather than via @bot.hybrid_command
# at module scope (the real limiter only exists after quickstart() runs).
bot.hybrid_command(name="ping", description="Replies with pong")(
    rate_limited("ping", rate_limiter=limiter)(_ping)
)

setup_warn(bot, store=warn_store, audit_logger=audit_logger)


async def on_automod_violation(message: discord.Message, reason: str) -> None:
    """automod detects, this remembers (warn) and lets the dashboard-
    configured ladder decide the punishment (escalation) -- see
    examples/hybrid_moderation for the same pattern, explained in depth."""
    if message.guild is None or not isinstance(message.author, discord.Member):
        return
    await warn_store.add(
        WarnRecord(
            guild_id=message.guild.id,
            user_id=message.author.id,
            moderator_id=message.guild.me.id,
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
    audit_logger=audit_logger,
)


# -- a small custom endpoint for the console: extras.warn ships storage +
# a command, not a dashboard API, so listing warnings over HTTP is exactly
# the kind of thing you write yourself. --
@app.get("/api/guilds/{guild_id}/warnings/{user_id}")
async def list_warnings(
    guild_id: int,
    user_id: int,
    _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
) -> list[dict]:
    records = await warn_store.list_for_user(guild_id, user_id)
    return [
        {
            "reason": r.reason,
            "moderator_id": r.moderator_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


# -- the one-page clickable test console --
_CONSOLE_HTML = Path(__file__).parent / "console.html"


@app.get("/console")
async def console() -> FileResponse:
    return FileResponse(_CONSOLE_HTML)
