from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from discord.ext import commands as dpy_commands
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.audit import AuditLogger, build_audit_log_router
from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import AppRoleCache, GuildMemberCache, build_app_roles_router
from discord_webapi.commands import CommandRegistry, build_commands_router
from discord_webapi.storage import MemoryAuditStore, MemoryAuthzStore, MemoryCommandConfigStore
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999


async def _build_app() -> FastAPI:
    app = FastAPI()
    transport = InProcessTransport()
    await transport.start()

    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name="kick", description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None: ...

    registry = CommandRegistry(bot, transport=transport, store=MemoryCommandConfigStore())
    await registry.register_all()

    authz_store = MemoryAuthzStore()
    audit_store = MemoryAuditStore()

    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)

    async def handle_get_member(payload: dict) -> dict:
        perms = discord.Permissions(manage_guild=True)
        return {"found": True, "role_ids": [], "permissions": perms.value}

    transport.register_handler("get_member", handle_get_member)

    app.state.discord_webapi_member_cache = GuildMemberCache(transport)
    app.state.discord_webapi_commands = registry
    app.state.discord_webapi_app_role_cache = AppRoleCache(authz_store)
    app.state.discord_webapi_audit_store = audit_store
    app.state.discord_webapi_audit_logger = AuditLogger(audit_store)
    app.include_router(build_commands_router())
    app.include_router(build_app_roles_router())
    app.include_router(build_audit_log_router())

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


async def test_command_patch_writes_an_audit_entry() -> None:
    app = await _build_app()
    with TestClient(app) as client:
        _log_in(client)

        patch_resp = client.patch(
            f"/api/guilds/{GUILD_ID}/commands/kick", json={"enabled": False}
        )
        assert patch_resp.status_code == 200

        log_resp = client.get(f"/api/guilds/{GUILD_ID}/audit-log")
        assert log_resp.status_code == 200
        entries = log_resp.json()
        assert len(entries) == 1
        assert entries[0]["action"] == "command.set_override"
        assert entries[0]["target"] == "kick"
        assert entries[0]["actor_user_id"] == 1


async def test_app_role_writes_are_audited() -> None:
    app = await _build_app()
    with TestClient(app) as client:
        _log_in(client)

        client.put(f"/api/guilds/{GUILD_ID}/app-roles/moderator", json={"user_ids": [1]})
        client.delete(f"/api/guilds/{GUILD_ID}/app-roles/moderator")

        log_resp = client.get(f"/api/guilds/{GUILD_ID}/audit-log")
        actions = [e["action"] for e in log_resp.json()]
        assert actions == ["app_role.delete", "app_role.set"]  # newest first
