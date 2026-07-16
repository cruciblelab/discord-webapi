from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.escalation import (
    EscalationEngine,
    MemoryEscalationRuleStore,
    MemoryViolationStore,
    build_escalation_router,
)
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_app(*, manage_guild: bool = True) -> tuple[FastAPI, EscalationEngine]:
    app = FastAPI()
    transport = InProcessTransport()
    engine = EscalationEngine(transport, MemoryEscalationRuleStore(), MemoryViolationStore())

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
    app.state.discord_webapi_escalation_engine = engine
    app.include_router(build_escalation_router())
    return app, engine


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


def test_list_all_rules_starts_empty() -> None:
    app, _engine = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/escalation-rules")

    assert resp.status_code == 200
    assert resp.json() == []


def test_set_rule_creates_and_returns_it() -> None:
    app, _engine = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.put(
        f"/api/guilds/{GUILD_ID}/escalation-rules/warn/3",
        json={"action": "timeout", "action_minutes": 10, "reason": "spam"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "warn"
    assert body["threshold"] == 3
    assert body["action"] == "timeout"
    assert body["action_minutes"] == 10


def test_list_rules_for_key() -> None:
    app, _engine = _build_app()
    client = TestClient(app)
    _log_in(client)
    client.put(
        f"/api/guilds/{GUILD_ID}/escalation-rules/warn/3",
        json={"action": "timeout"},
    )
    client.put(
        f"/api/guilds/{GUILD_ID}/escalation-rules/automod.spam/1",
        json={"action": "kick"},
    )

    resp = client.get(f"/api/guilds/{GUILD_ID}/escalation-rules/warn")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["key"] == "warn"


async def test_set_rule_takes_effect_immediately_on_the_engine() -> None:
    app, engine = _build_app()
    client = TestClient(app)
    _log_in(client)

    client.put(
        f"/api/guilds/{GUILD_ID}/escalation-rules/warn/1",
        json={"action": "none"},
    )

    rules = await engine.list_rules(GUILD_ID, "warn")
    assert len(rules) == 1
    assert rules[0].threshold == 1


def test_delete_rule_removes_it() -> None:
    app, _engine = _build_app()
    client = TestClient(app)
    _log_in(client)
    client.put(
        f"/api/guilds/{GUILD_ID}/escalation-rules/warn/3",
        json={"action": "timeout"},
    )

    resp = client.delete(f"/api/guilds/{GUILD_ID}/escalation-rules/warn/3")

    assert resp.status_code == 204
    list_resp = client.get(f"/api/guilds/{GUILD_ID}/escalation-rules/warn")
    assert list_resp.json() == []


def test_escalation_api_requires_manage_guild_permission() -> None:
    app, _engine = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/escalation-rules")

    assert resp.status_code == 403


def test_escalation_api_requires_authentication() -> None:
    app, _engine = _build_app()
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/escalation-rules")

    assert resp.status_code == 401
