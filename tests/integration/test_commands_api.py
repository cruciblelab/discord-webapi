from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from discord.ext import commands as dpy_commands
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.commands.api import build_commands_router
from discord_webapi.commands.ratelimit import TokenBucketLimiter
from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.storage import MemoryCommandConfigStore
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


def _build_bot() -> dpy_commands.Bot:
    intents = discord.Intents.default()
    bot = dpy_commands.Bot(command_prefix="!", intents=intents)

    @bot.hybrid_command(name="kick", description="Kick a member")
    async def kick(
        ctx: dpy_commands.Context, member: discord.Member, reason: str | None = None
    ) -> None:
        ...

    return bot


def _build_app(
    *, patch_rate_limiter: TokenBucketLimiter | None = None, manage_guild: bool = True
) -> tuple[FastAPI, CommandRegistry, InProcessTransport]:
    app = FastAPI()
    transport = InProcessTransport()
    store = MemoryCommandConfigStore()
    bot = _build_bot()
    registry = CommandRegistry(bot, transport=transport, store=store)

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
    app.state.discord_webapi_commands = registry

    app.include_router(build_commands_router(patch_rate_limiter=patch_rate_limiter))
    return app, registry, transport


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


async def test_list_commands_returns_registered_kick_command() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/commands")

    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "kick" in names
    kick = next(c for c in resp.json() if c["name"] == "kick")
    assert kick["enabled"] is True
    assert kick["is_slash"] is True
    assert kick["is_prefix"] is True


async def test_patch_disables_command_live_without_restart() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    patch_resp = client.patch(f"/api/guilds/{GUILD_ID}/commands/kick", json={"enabled": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False

    # No restart: the same registry instance already reflects the change.
    assert registry.is_enabled(GUILD_ID, "kick") is False

    list_resp = client.get(f"/api/guilds/{GUILD_ID}/commands")
    kick = next(c for c in list_resp.json() if c["name"] == "kick")
    assert kick["enabled"] is False


async def test_patch_sets_cooldown_and_enforces_it_live() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    patch_resp = client.patch(
        f"/api/guilds/{GUILD_ID}/commands/kick",
        json={"enabled": True, "cooldown_seconds": 60, "cooldown_uses": 1},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["cooldown_seconds"] == 60
    assert patch_resp.json()["cooldown_uses"] == 1

    list_resp = client.get(f"/api/guilds/{GUILD_ID}/commands")
    kick = next(c for c in list_resp.json() if c["name"] == "kick")
    assert kick["cooldown_seconds"] == 60
    assert kick["cooldown_uses"] == 1

    # No restart: the registry's cooldown bucket is live immediately.
    fake_ctx = SimpleNamespace(author=SimpleNamespace(id=1))
    assert registry._check_cooldown(GUILD_ID, "kick", fake_ctx) is None


async def test_patch_rejects_unpaired_cooldown_fields() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    resp = client.patch(
        f"/api/guilds/{GUILD_ID}/commands/kick",
        json={"enabled": True, "cooldown_seconds": 60},
    )

    assert resp.status_code == 422


async def test_patch_unknown_command_returns_404() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    resp = client.patch(f"/api/guilds/{GUILD_ID}/commands/does-not-exist", json={"enabled": False})

    assert resp.status_code == 404


async def test_commands_api_requires_manage_guild_permission() -> None:
    app, registry, _transport = _build_app(manage_guild=False)
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/commands")

    assert resp.status_code == 403


async def test_commands_api_requires_authentication() -> None:
    app, registry, _transport = _build_app()
    await registry.register_all()
    client = TestClient(app)

    resp = client.get(f"/api/guilds/{GUILD_ID}/commands")

    assert resp.status_code == 401


async def test_patch_rate_limit_returns_429_when_exceeded() -> None:
    app, registry, _transport = _build_app(patch_rate_limiter=TokenBucketLimiter(1, 60.0))
    await registry.register_all()
    client = TestClient(app)
    _log_in(client)

    first = client.patch(f"/api/guilds/{GUILD_ID}/commands/kick", json={"enabled": False})
    second = client.patch(f"/api/guilds/{GUILD_ID}/commands/kick", json={"enabled": True})

    assert first.status_code == 200
    assert second.status_code == 429
