"""Minimal end-to-end demo of discord-webapi's v0.1 core: Discord OAuth2
login, a browser dashboard listing guild members with their roles, listing
the bot's registered commands, and disabling one live (no bot restart) via
`PATCH /api/guilds/{id}/commands/...`.

Run:
    pip install -e ".[sql]"                     # from the repo root
    cp examples/single_process_bot/.env.example examples/single_process_bot/.env
    # fill in .env (see comments in that file), then:
    set -a && source examples/single_process_bot/.env && set +a
    uvicorn main:app --reload --app-dir examples/single_process_bot

Try it:
    1. Invite the bot to a test server with the "applications.commands" and
       "bot" scopes (Discord Developer Portal -> OAuth2 -> URL Generator).
    2. Open http://localhost:8000/dashboard in a browser, log in with
       Discord, paste in the test server's Guild ID, and load its members —
       each row shows their roles. (No ban/kick actions — view-only.)
    3. GET /api/guilds/{your_guild_id}/commands — lists "ping" and "say"
       (requires "Manage Server" permission in that guild).
    4. PATCH /api/guilds/{your_guild_id}/commands/ping {"enabled": false}
       — then try `/ping` in Discord: it's rejected without a bot restart.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import discord
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from discord_webapi import DiscordAuth, DiscordWebAPI, InProcessTransport

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DASHBOARD_BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")
DWA_FERNET_KEY = os.environ["DWA_FERNET_KEY"].encode()

# Intents.members is required so `guild.get_member(...)` is populated in the
# bot's Gateway cache — that cache is what authz.GuildMemberCache reads via
# the transport's `get_member` RPC, never a REST call. Also enable the
# "Server Members Intent" toggle for this bot in the Developer Portal.
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.hybrid_command(name="ping", description="Replies with pong")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")


@bot.hybrid_command(name="say", description="Echoes back a message")
async def say(ctx: commands.Context, message: str) -> None:
    await ctx.reply(message)


transport = InProcessTransport()

auth = DiscordAuth(
    client_id=DISCORD_CLIENT_ID,
    client_secret=DISCORD_CLIENT_SECRET,
    redirect_uri=f"{DASHBOARD_BASE_URL}/auth/discord/callback",
    encryption_keys=DWA_FERNET_KEY,
    cookie_secure=DASHBOARD_BASE_URL.startswith("https://"),
    login_success_redirect="/",
)

api = DiscordWebAPI(bot=bot, transport=transport, auth=auth)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with api.lifespan(DISCORD_BOT_TOKEN):
        yield


app = FastAPI(title="discord-webapi single-process example", lifespan=lifespan)
api.install(app)


_DASHBOARD_HTML = (Path(__file__).parent / "static" / "dashboard.html").read_text()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _DASHBOARD_HTML


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return _DASHBOARD_HTML
