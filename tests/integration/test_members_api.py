from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.members import build_members_router, install_member_listing
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


class _FakeRole:
    def __init__(self, id_: int, name: str, default: bool = False) -> None:
        self.id = id_
        self.name = name
        self._default = default

    def is_default(self) -> bool:
        return self._default


class _FakeMember:
    def __init__(self, id_: int, username: str, display_name: str, roles: list[_FakeRole]) -> None:
        self.id = id_
        self._username = username
        self.display_name = display_name
        self.roles = roles
        self.joined_at = None
        self.display_avatar = None

    def __str__(self) -> str:
        return self._username


def _build_app(*, manage_guild: bool = True) -> tuple[FastAPI, InProcessTransport]:
    app = FastAPI()
    transport = InProcessTransport()

    everyone = _FakeRole(1, "@everyone", default=True)
    admin = _FakeRole(2, "Admin")
    members = [_FakeMember(42, "tester#0", "Tester", [everyone, admin])]

    def get_guild(gid: int) -> SimpleNamespace | None:
        return SimpleNamespace(members=members) if gid == GUILD_ID else None

    fake_bot = SimpleNamespace(get_guild=get_guild)
    install_member_listing(fake_bot, transport)  # type: ignore[arg-type]

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
    app.state.discord_webapi_transport = transport
    app.include_router(build_members_router())
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
    respx_mock.get(GUILDS_URL).mock(return_value=httpx.Response(200, json=[]))


def _log_in(client: TestClient) -> None:
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    with respx.mock:
        _mock_discord_endpoints(respx.mock)
        client.get(f"/auth/discord/callback?code=abc&state={state}", follow_redirects=False)


def test_list_members_returns_roster_with_roles() -> None:
    app, _transport = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/members")

    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["display_name"] == "Tester"
    assert members[0]["role_names"] == ["Admin"]


def test_list_members_unknown_guild_returns_404() -> None:
    app, _transport = _build_app()
    client = TestClient(app)
    _log_in(client)

    resp = client.get("/api/guilds/123456/members")

    assert resp.status_code == 404


def test_list_members_requires_manage_guild_permission() -> None:
    app, _transport = _build_app(manage_guild=False)
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/members")

    assert resp.status_code == 403


def test_list_members_requires_authentication() -> None:
    app, _transport = _build_app()
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/members")

    assert resp.status_code == 401
