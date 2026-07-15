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
from fastapi import Depends
from fastapi.responses import HTMLResponse

from discord_webapi import DiscordWebAPI
from discord_webapi.authz import ChannelContext, require_channel_permission
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
# login, the browser lands on /mobile-login-done (defined below) with
# `?session_id=...` in the URL, which that route renders as a big,
# selectable/copyable block instead of leaving you to squint at a
# truncated address bar.
_base_url = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")

# Global slash-command sync can take up to an hour to show up everywhere;
# set TEST_GUILD_ID (your test server's ID) in .env for near-instant sync
# to just that one guild while you're testing. Leave unset for a normal
# global sync.
_test_guild_id = os.environ.get("TEST_GUILD_ID")

app = DiscordWebAPI.quickstart(
    bot=bot,
    sync_guild_id=int(_test_guild_id) if _test_guild_id else None,
    enable_websocket=True,
    enable_audit_log=True,
    enable_cookie_consent=True,
    cookie_consent_message=(
        "This test dashboard uses a cookie to keep your login session. "
        "Continuing means you're OK with that."
    ),
    mobile_redirect_uri=f"{_base_url}/mobile-login-done",
)


@app.get("/mobile-login-done", response_class=HTMLResponse, include_in_schema=False)
async def mobile_login_done(session_id: str = "", expires_at: str = "") -> str:
    """Lands here after `/auth/discord/login?mobile=true` completes. Not
    part of the library -- just this example's own tiny page so you don't
    have to fight a mobile browser's address bar to read `session_id` out
    of the URL. If `session_id` shows up empty below, the redirect you
    followed didn't actually come from a real mobile login just now (e.g.
    you typed/pasted this URL by hand, or the `mobile=true` query param
    got mangled on the way in -- try the "Mobil giriş" button on `/` again
    instead of typing the URL).
    """
    if not session_id:
        return (
            "<p>session_id boş geldi -- bu sayfaya gerçek bir mobil "
            "login yönlendirmesiyle gelmedin. <a href='/'>Baştan dene</a>: "
            "ana sayfadaki \"Mobil giriş (session_id al)\" butonuna tıkla, "
            "URL'i elle yazma/yapıştırma.</p>"
        )
    return f"""
    <p>Giriş başarılı. Aşağıdaki değeri (dokunup basılı tutup "Kopyala" ile)
    kopyala -- bunu her istekte <code>Authorization: Bearer &lt;değer&gt;</code>
    header'ı olarak kullanacaksın.</p>
    <p style="font-size:1.1rem; word-break:break-all; background:#eee;
       padding:0.75rem; border-radius:6px;">
      <code id="sid">{session_id}</code>
    </p>
    <p style="font-size:0.85rem; color:#555;">Geçerlilik: {expires_at}</p>
    """


@app.get("/api/guilds/{guild_id}/channels/{channel_id}/can-send")
async def can_send_in_channel(
    guild_id: int,
    channel_id: int,
    ctx: ChannelContext = Depends(require_channel_permission("send_messages")),
) -> dict:
    """Demo endpoint for the new channel-level permission overwrite
    feature (v0.4): unlike `require_guild_permission`, this checks
    *effective* permissions in this specific channel -- if the channel has
    an overwrite denying `send_messages` to this member's role, this 403s
    even though they might have `send_messages` at the guild level."""
    return {"guild_id": guild_id, "channel_id": channel_id, "user_id": ctx.user.id}
