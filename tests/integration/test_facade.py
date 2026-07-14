from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from discord.ext import commands as dpy_commands
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi import DiscordAuth, DiscordWebAPI, InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"


def _build_bot() -> dpy_commands.Bot:
    bot = dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )

    @bot.hybrid_command(name="ping", description="Ping the bot")
    async def ping(ctx: dpy_commands.Context) -> None:
        ...

    return bot


def _build_app() -> tuple[FastAPI, DiscordWebAPI]:
    app = FastAPI()
    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth)
    api.install(app)
    return app, api


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


async def test_facade_wires_auth_and_commands_routes() -> None:
    app, api = _build_app()
    await api._on_ready()  # simulates the bot's on_ready firing

    async def handle_get_member(payload: dict) -> dict:
        return {"found": True, "role_ids": [], "permissions": discord.Permissions.all().value}

    api.transport._handlers.pop("get_member", None)
    api.transport.register_handler("get_member", handle_get_member)

    client = TestClient(app)
    _log_in(client)

    resp = client.get("/api/guilds/123/commands")

    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "ping" in names


async def test_facade_registers_member_lookup_handler() -> None:
    _app, api = _build_app()

    response = await api.transport.request("get_member", {"guild_id": 1, "user_id": 2})

    assert response == {"found": False}
