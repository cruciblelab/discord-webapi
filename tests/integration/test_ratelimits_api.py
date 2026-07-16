from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.ratelimits import GuildRateLimiter, build_ratelimits_router
from discord_webapi.storage import MemoryRateLimitStore
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_app(*, manage_guild: bool = True) -> tuple[FastAPI, GuildRateLimiter]:
    app = FastAPI()
    transport = InProcessTransport()
    limiter = GuildRateLimiter(transport, MemoryRateLimitStore())

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
    app.state.discord_webapi_ratelimiter = limiter
    app.include_router(build_ratelimits_router())
    return app, limiter


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


def test_list_rules_starts_empty() -> None:
    app, _limiter = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/ratelimits")

    assert resp.status_code == 200
    assert resp.json() == []


def test_set_rule_creates_and_returns_it() -> None:
    app, _limiter = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.put(
        f"/api/guilds/{GUILD_ID}/ratelimits/automod.spam",
        json={"max_calls": 3, "per_seconds": 15.0},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "automod.spam"
    assert body["max_calls"] == 3
    assert body["per_seconds"] == 15.0


async def test_set_rule_takes_effect_immediately_on_the_limiter() -> None:
    app, limiter = _build_app()
    client = TestClient(app)
    _log_in(client)

    client.put(
        f"/api/guilds/{GUILD_ID}/ratelimits/automod.spam",
        json={"max_calls": 1, "per_seconds": 60.0},
    )

    assert await limiter.check(GUILD_ID, "automod.spam") is True
    assert await limiter.check(GUILD_ID, "automod.spam") is False


def test_delete_rule_removes_it() -> None:
    app, _limiter = _build_app()
    client = TestClient(app)
    _log_in(client)
    client.put(
        f"/api/guilds/{GUILD_ID}/ratelimits/automod.spam",
        json={"max_calls": 3, "per_seconds": 15.0},
    )

    resp = client.delete(f"/api/guilds/{GUILD_ID}/ratelimits/automod.spam")

    assert resp.status_code == 204
    list_resp = client.get(f"/api/guilds/{GUILD_ID}/ratelimits")
    assert list_resp.json() == []


def test_ratelimits_api_requires_manage_guild_permission() -> None:
    app, _limiter = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/ratelimits")

    assert resp.status_code == 403


def test_ratelimits_api_requires_authentication() -> None:
    app, _limiter = _build_app()
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/ratelimits")

    assert resp.status_code == 401
