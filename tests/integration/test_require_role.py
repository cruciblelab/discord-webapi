"""`require_role` (a Discord-native role id check, distinct from
`require_app_role`'s bot-owned roles) had no test coverage at all."""

from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildContext, GuildMemberCache, require_role
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999
MOD_ROLE_ID = 12345


def _build_app(
    *, member_role_ids: list[int] | None = None, administrator: bool = False
) -> FastAPI:
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
        perms = discord.Permissions(administrator=administrator)
        return {"found": True, "role_ids": member_role_ids or [], "permissions": perms.value}

    transport.register_handler("get_member", handle_get_member)
    app.state.discord_webapi_member_cache = GuildMemberCache(transport)

    @app.get("/api/guilds/{guild_id}/mod-only")
    async def mod_only(
        guild_id: int, ctx: GuildContext = Depends(require_role(role_id=MOD_ROLE_ID))
    ) -> dict:
        return {"ok": True}

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


def test_require_role_allows_a_member_with_the_role() -> None:
    app = _build_app(member_role_ids=[MOD_ROLE_ID])
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 200


def test_require_role_rejects_a_member_without_the_role() -> None:
    app = _build_app(member_role_ids=[999999])
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 403


def test_require_role_allows_an_administrator_without_the_role() -> None:
    """Matches the other require_* dependencies: administrator always passes."""
    app = _build_app(member_role_ids=[], administrator=True)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 200


def test_require_role_rejects_non_members() -> None:
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
        return {"found": False}

    transport.register_handler("get_member", handle_get_member)
    app.state.discord_webapi_member_cache = GuildMemberCache(transport)

    @app.get("/api/guilds/{guild_id}/mod-only")
    async def mod_only(
        guild_id: int, ctx: GuildContext = Depends(require_role(role_id=MOD_ROLE_ID))
    ) -> dict:
        return {"ok": True}

    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 403


def test_require_role_requires_authentication() -> None:
    app = _build_app(member_role_ids=[MOD_ROLE_ID])
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 401
