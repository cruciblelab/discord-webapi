"""Comprehensive test bed: every optional feature turned on at once, so
one bot exercises the whole library surface -- auth (browser + mobile),
live command enable/disable + cooldowns, AppRole, the WebSocket relay,
the audit log, the cookie-consent banner, and every builtin command.

This is deliberately more than a "getting started" example -- see
`examples/single_process_bot/` for that. This one exists to be poked at
manually (see `../../TESTING.md` for a step-by-step checklist) and to
give the WebSocket relay a real client to talk to (`ws_test_client.py`
in this folder).

Run:
    pip install -e ".[sql]"
    cp examples/full_featured_bot/.env.example examples/full_featured_bot/.env
    # fill in .env, then:
    set -a && source examples/full_featured_bot/.env && set +a
    uvicorn main:app --reload --app-dir examples/full_featured_bot
"""

import os

from discord.ext import commands

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents
from discord_webapi.builtins.ban import setup as setup_ban
from discord_webapi.builtins.kick import setup as setup_kick
from discord_webapi.builtins.timeout import setup as setup_timeout
from discord_webapi.builtins.warn import setup as setup_warn
from discord_webapi.builtins.welcome import setup as setup_welcome

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)


@bot.hybrid_command(name="ping", description="Replies with pong")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")


@bot.hybrid_command(name="say", description="Echoes back a message")
async def say(ctx: commands.Context, message: str) -> None:
    await ctx.reply(message)


# Every builtin, wired with its defaults -- see discord_webapi/builtins/
# README.md for what each keyword argument changes. Feel free to comment
# any of these out or pass different kwargs while testing.
setup_ban(bot)
setup_kick(bot)
setup_timeout(bot)
setup_warn(bot, auto_timeout_after=3, auto_timeout_minutes=10)
# channel_id=None means this does nothing yet (see welcome.py's docstring)
# -- it never guesses a channel. Set it to a real channel ID from your
# test server to actually see the welcome message on a new member join.
setup_welcome(bot, channel_id=None)

# Enables GET /auth/discord/login?mobile=true -- useful for testing
# without ever reading a cookie out of a mobile browser: after Discord
# login, the browser lands here with `?session_id=...` right there in the
# URL to copy, then you send it as `Authorization: Bearer <session_id>`
# on every request (curl, ws_test_client.py, ...) instead of a cookie.
# There's no real page at this path -- you're only reading the URL bar,
# a 404 here is expected and fine.
_base_url = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")

app = DiscordWebAPI.quickstart(
    bot=bot,
    enable_websocket=True,
    enable_audit_log=True,
    enable_cookie_consent=True,
    cookie_consent_message=(
        "This test dashboard uses a cookie to keep your login session. "
        "Continuing means you're OK with that."
    ),
    mobile_redirect_uri=f"{_base_url}/mobile-login-done",
)
