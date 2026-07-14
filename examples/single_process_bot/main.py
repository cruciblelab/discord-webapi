"""Minimal end-to-end demo of discord-webapi's v0.1 core, using
`DiscordWebAPI.quickstart()` -- the whole web/auth/storage side (OAuth2
login, a member/role dashboard, live command enable/disable) in a handful
of lines on top of whatever discord.py commands you already write.

Sessions and command overrides are stored in a local SQLite file
(dashboard.sqlite3, created automatically next to this file), so logins
and command toggles survive a restart.

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

from discord.ext import commands

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)


@bot.hybrid_command(name="ping", description="Replies with pong")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")


@bot.hybrid_command(name="say", description="Echoes back a message")
async def say(ctx: commands.Context, message: str) -> None:
    await ctx.reply(message)


app = DiscordWebAPI.quickstart(bot=bot)
