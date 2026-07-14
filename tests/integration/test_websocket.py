"""Auth/permission gating for the opt-in WebSocket command-config relay.

The actual live-relay round trip (connect -> PATCH a command elsewhere ->
receive the change over the socket) isn't exercised here: Starlette's
TestClient runs each WebSocket connection on its own background thread/
event loop, while InProcessTransport's `asyncio.Queue` and `create_task`
calls are pinned to whichever loop was running when `publish()` was
called -- mixing the two deadlocks rather than failing loudly. That full
round trip is exactly the kind of thing to verify by hand (two browser
tabs, toggle a command in one, watch it update in the other) -- see the
manual test plan.
"""

from urllib.parse import parse_qs, urlparse

import discord
import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.transport import InProcessTransport
from discord_webapi.web import build_commands_websocket_router

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_app(*, manage_guild: bool = True) -> FastAPI:
    app = FastAPI()
    transport = InProcessTransport()

    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)

    async def handle_get_member(payload: dict) -> dict:
        perms = discord.Permissions(manage_guild=manage_guild)
        return {"found": True, "role_ids": [], "permissions": perms.value}

    transport.register_handler("get_member", handle_get_member)

    app.state.discord_webapi_member_cache = GuildMemberCache(transport)
    app.include_router(build_commands_websocket_router(transport))
    return app


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


def test_websocket_requires_authentication() -> None:
    app = _build_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/guilds/{GUILD_ID}/commands/stream"):
            pass

    assert exc_info.value.code == 4401


def test_websocket_requires_manage_guild_permission() -> None:
    app = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/guilds/{GUILD_ID}/commands/stream"):
            pass

    assert exc_info.value.code == 4403


def test_websocket_accepts_authorized_connection() -> None:
    app = _build_app()
    client = TestClient(app)
    _log_in(client)

    # No exception on connect/disconnect -- the handshake and permission
    # check both passed.
    with client.websocket_connect(f"/api/guilds/{GUILD_ID}/commands/stream"):
        pass
