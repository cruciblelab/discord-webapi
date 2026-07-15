from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import ChannelContext, ChannelPermissionCache, require_channel_permission
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999
CHANNEL_ID = 555


def _build_app(*, found: bool = True, send_messages: bool = True) -> FastAPI:
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

    async def handle_get_channel_permissions(payload: dict) -> dict:
        if not found:
            return {"found": False}
        perms = discord.Permissions(send_messages=send_messages)
        return {"found": True, "permissions": perms.value}

    transport.register_handler("get_channel_permissions", handle_get_channel_permissions)
    app.state.discord_webapi_channel_permission_cache = ChannelPermissionCache(transport)

    @app.get("/api/guilds/{guild_id}/channels/{channel_id}/send-only")
    async def send_only(
        guild_id: int,
        channel_id: int,
        ctx: ChannelContext = Depends(require_channel_permission("send_messages")),
    ) -> dict:
        return {"user_id": ctx.user.id, "channel_id": ctx.channel_id}

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


def test_require_channel_permission_allows_when_permission_present() -> None:
    app = _build_app(send_messages=True)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/channels/{CHANNEL_ID}/send-only")

    assert resp.status_code == 200
    assert resp.json() == {"user_id": 1, "channel_id": CHANNEL_ID}


def test_require_channel_permission_rejects_when_overwrite_denies() -> None:
    """The scenario this feature exists for: a guild-level permission the
    member does have, but a channel-specific overwrite takes it away."""
    app = _build_app(send_messages=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/channels/{CHANNEL_ID}/send-only")

    assert resp.status_code == 403


def test_require_channel_permission_rejects_when_channel_not_found() -> None:
    app = _build_app(found=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/channels/{CHANNEL_ID}/send-only")

    assert resp.status_code == 403


def test_require_channel_permission_requires_authentication() -> None:
    app = _build_app()
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/channels/{CHANNEL_ID}/send-only")

    assert resp.status_code == 401
