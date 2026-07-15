from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.guilds import build_guilds_router
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

MANAGEABLE_GUILD_ID = 999
NO_PERMISSION_GUILD_ID = 111
BOT_NOT_PRESENT_GUILD_ID = 222


def _build_app() -> tuple[FastAPI, InProcessTransport]:
    app = FastAPI()
    transport = InProcessTransport()

    async def handle_list_manageable_guilds(payload: dict) -> dict:
        guild_ids = payload["guild_ids"]
        guilds = []
        if MANAGEABLE_GUILD_ID in guild_ids:
            perms = discord.Permissions(manage_guild=True)
            guilds.append(
                {
                    "guild_id": MANAGEABLE_GUILD_ID,
                    "name": "Manageable Guild",
                    "icon_url": None,
                    "permissions": perms.value,
                }
            )
        if NO_PERMISSION_GUILD_ID in guild_ids:
            perms = discord.Permissions(manage_guild=False)
            guilds.append(
                {
                    "guild_id": NO_PERMISSION_GUILD_ID,
                    "name": "No Permission Guild",
                    "icon_url": None,
                    "permissions": perms.value,
                }
            )
        # BOT_NOT_PRESENT_GUILD_ID is deliberately never appended -- the bot
        # isn't in that guild, matching list_manageable_guilds' own contract.
        return {"guilds": guilds}

    transport.register_handler("list_manageable_guilds", handle_list_manageable_guilds)

    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)

    app.state.discord_webapi_transport = transport
    app.include_router(build_guilds_router())
    return app, transport


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
    respx_mock.get(GUILDS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": str(MANAGEABLE_GUILD_ID)},
                {"id": str(NO_PERMISSION_GUILD_ID)},
                {"id": str(BOT_NOT_PRESENT_GUILD_ID)},
            ],
        )
    )


def _log_in(client: TestClient) -> None:
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    with respx.mock:
        _mock_discord_endpoints(respx.mock)
        client.get(f"/auth/discord/callback?code=abc&state={state}", follow_redirects=False)


def test_list_guilds_returns_only_manageable_guilds() -> None:
    app, _transport = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.get("/api/guilds")

    assert resp.status_code == 200
    guilds = resp.json()
    assert len(guilds) == 1
    assert guilds[0]["guild_id"] == MANAGEABLE_GUILD_ID
    assert guilds[0]["name"] == "Manageable Guild"


def test_list_guilds_requires_authentication() -> None:
    app, _transport = _build_app()
    client = TestClient(app)

    resp = client.get("/api/guilds")

    assert resp.status_code == 401
