"""Tests for the split bot/web deployment shape (`DiscordWebAPI.for_bot_process`
/ `for_web_process`) -- a big bot running the Discord Gateway connection in
one process and the FastAPI dashboard scaled out as separate replicas.

The two `DiscordWebAPI` objects below deliberately never share a Python
object with each other (only `transport`, standing in for `RedisTransport`
across real machines) -- this is what proves the web side's routers work
purely over Transport RPC, with no local `CommandRegistry` reference.
"""

from urllib.parse import parse_qs, urlparse

import discord
import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from discord.ext import commands as dpy_commands
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi import DiscordAuth, DiscordWebAPI, InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_bot() -> dpy_commands.Bot:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name="kick", description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None: ...

    return bot


def _build_split_app() -> tuple[FastAPI, DiscordWebAPI, DiscordWebAPI]:
    # A shared InProcessTransport stands in for RedisTransport shared
    # across machines -- what matters is that `bot_side`/`web_side` are
    # two separate DiscordWebAPI instances (as they would be, in two
    # separate processes) that never reference each other directly.
    transport = InProcessTransport()
    bot = _build_bot()
    bot_side = DiscordWebAPI.for_bot_process(bot=bot, transport=transport, sync_commands=False)

    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    web_side = DiscordWebAPI.for_web_process(transport=transport, auth=auth)

    app = FastAPI()
    web_side.install(app)
    return app, bot_side, web_side


def _mock_discord_endpoints(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 604800,
                "token_type": "Bearer",
            },
        )
    )
    respx_mock.get(ME_URL).mock(
        return_value=httpx.Response(200, json={"id": "1", "username": "admin"})
    )
    respx_mock.get(GUILDS_URL).mock(return_value=httpx.Response(200, json=[]))


def _log_in(client: TestClient) -> None:
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    with respx.mock:
        _mock_discord_endpoints(respx.mock)
        client.get(f"/auth/discord/callback?code=abc&state={state}", follow_redirects=False)


async def test_for_web_process_has_no_local_registry() -> None:
    """The whole point of the split: the web-side object must not own a
    live CommandRegistry -- it can only see command state through the
    Transport RPC bridge the bot-side process installs."""
    _app, _bot_side, web_side = _build_split_app()

    assert web_side.registry is None
    assert web_side.bot is None


async def test_for_bot_process_has_no_auth() -> None:
    _app, bot_side, _web_side = _build_split_app()

    assert bot_side.auth is None
    with pytest.raises(RuntimeError, match="install"):
        bot_side.install(FastAPI())


async def test_commands_api_works_across_the_split_via_transport_only() -> None:
    app, bot_side, _web_side = _build_split_app()
    await bot_side._on_ready()  # simulates the bot process's on_ready firing

    async def handle_get_member(payload: dict) -> dict:
        return {"found": True, "role_ids": [], "permissions": discord.Permissions.all().value}

    bot_side.transport._handlers.pop("get_member", None)
    bot_side.transport.register_handler("get_member", handle_get_member)

    client = TestClient(app)
    _log_in(client)

    list_resp = client.get(f"/api/guilds/{GUILD_ID}/commands")
    assert list_resp.status_code == 200
    names = {c["name"] for c in list_resp.json()}
    assert "kick" in names

    patch_resp = client.patch(f"/api/guilds/{GUILD_ID}/commands/kick", json={"enabled": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False

    # No restart, no shared object: the bot-side registry (a completely
    # separate DiscordWebAPI instance) already reflects the write, purely
    # through the store + command_config_changed event.
    assert bot_side.registry is not None
    assert bot_side.registry.is_enabled(GUILD_ID, "kick") is False


async def test_lifespan_requires_a_bot() -> None:
    _app, _bot_side, web_side = _build_split_app()

    with pytest.raises(RuntimeError, match="bot"):
        web_side.lifespan("fake-token")

    # web_lifespan() is the one it should use instead -- just check it
    # constructs without error, actually entering it needs a live Redis
    # connection for RedisTransport, out of scope for this test.
    web_side.web_lifespan()
