from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import (
    AppRoleCache,
    GuildContext,
    GuildMemberCache,
    build_app_roles_router,
    require_app_role,
)
from discord_webapi.storage import MemoryAuthzStore
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_app(
    *,
    manage_guild: bool = True,
    administrator: bool = False,
    member_role_ids: list[int] | None = None,
) -> tuple[FastAPI, AppRoleCache]:
    app = FastAPI()
    transport = InProcessTransport()
    authz_store = MemoryAuthzStore()
    app_role_cache = AppRoleCache(authz_store)

    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)

    async def handle_get_member(payload: dict) -> dict:
        perms = discord.Permissions(manage_guild=manage_guild, administrator=administrator)
        return {"found": True, "role_ids": member_role_ids or [], "permissions": perms.value}

    transport.register_handler("get_member", handle_get_member)

    app.state.discord_webapi_member_cache = GuildMemberCache(transport)
    app.state.discord_webapi_app_role_cache = app_role_cache
    app.include_router(build_app_roles_router())

    @app.get("/api/guilds/{guild_id}/mod-only")
    async def mod_only(
        guild_id: int, ctx: GuildContext = Depends(require_app_role("moderator"))
    ) -> dict:
        return {"user_id": ctx.user.id}

    return app, app_role_cache


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


def test_set_and_list_app_roles() -> None:
    app, _cache = _build_app()
    client = TestClient(app)
    _log_in(client)

    put_resp = client.put(
        f"/api/guilds/{GUILD_ID}/app-roles/moderator",
        json={"discord_role_ids": [10], "user_ids": [1]},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["user_ids"] == [1]

    list_resp = client.get(f"/api/guilds/{GUILD_ID}/app-roles")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["name"] == "moderator"


def test_delete_app_role() -> None:
    app, _cache = _build_app()
    client = TestClient(app)
    _log_in(client)
    client.put(f"/api/guilds/{GUILD_ID}/app-roles/moderator", json={"user_ids": [1]})

    delete_resp = client.delete(f"/api/guilds/{GUILD_ID}/app-roles/moderator")
    assert delete_resp.status_code == 204

    list_resp = client.get(f"/api/guilds/{GUILD_ID}/app-roles")
    assert list_resp.json() == []


def test_app_roles_api_requires_manage_guild() -> None:
    app, _cache = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/app-roles")

    assert resp.status_code == 403


def test_require_app_role_allows_user_in_user_ids() -> None:
    app, cache = _build_app()
    client = TestClient(app)
    _log_in(client)
    # /auth/discord/me was mocked to id=1, so grant the app role to user 1.
    client.put(f"/api/guilds/{GUILD_ID}/app-roles/moderator", json={"user_ids": [1]})

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 200
    assert resp.json()["user_id"] == 1


def test_require_app_role_allows_user_via_discord_role() -> None:
    app, _cache = _build_app(manage_guild=True, member_role_ids=[555])
    client = TestClient(app)
    _log_in(client)
    client.put(f"/api/guilds/{GUILD_ID}/app-roles/moderator", json={"discord_role_ids": [555]})

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 200


def test_require_app_role_rejects_user_without_role() -> None:
    app, _cache = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)
    # No app role granted to user 1 at all.

    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")

    assert resp.status_code == 403


def test_require_app_role_manage_guild_alone_is_not_enough() -> None:
    app, _cache = _build_app(manage_guild=True, administrator=False)
    client = TestClient(app)
    _log_in(client)

    # No app role granted; manage_guild (unlike administrator) doesn't
    # bypass require_app_role -- only an explicit AppRole grant or
    # administrator does.
    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")
    assert resp.status_code == 403


def test_require_app_role_administrator_always_passes() -> None:
    app, _cache = _build_app(manage_guild=False, administrator=True)
    client = TestClient(app)
    _log_in(client)

    # No app role granted at all -- administrator alone must be enough.
    resp = client.get(f"/api/guilds/{GUILD_ID}/mod-only")
    assert resp.status_code == 200
