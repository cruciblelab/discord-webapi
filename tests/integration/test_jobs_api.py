import asyncio
from urllib.parse import parse_qs, urlparse

import discord
import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.authz import GuildMemberCache
from discord_webapi.jobs import InProcessJobQueue, build_jobs_router
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"

GUILD_ID = 999
OTHER_GUILD_ID = 111


def _build_app(*, manage_guild: bool = True) -> tuple[FastAPI, InProcessJobQueue]:
    app = FastAPI()
    transport = InProcessTransport()
    job_queue = InProcessJobQueue()

    async def handle_bulk_action(payload: dict) -> dict:
        return {"processed": payload.get("count", 0)}

    job_queue.register_worker("bulk_action", handle_bulk_action)

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
    app.state.discord_webapi_job_queue = job_queue
    app.include_router(build_jobs_router())
    return app, job_queue


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


async def test_enqueue_and_poll_job_until_it_succeeds() -> None:
    app, job_queue = _build_app()
    await job_queue.start()
    client = TestClient(app)
    _log_in(client)

    enqueue_resp = client.post(
        f"/api/guilds/{GUILD_ID}/jobs/bulk_action", json={"payload": {"count": 5}}
    )
    assert enqueue_resp.status_code == 202
    job_id = enqueue_resp.json()["job_id"]
    assert enqueue_resp.json()["state"] == "pending"

    for _ in range(50):
        status_resp = client.get(f"/api/guilds/{GUILD_ID}/jobs/{job_id}")
        assert status_resp.status_code == 200
        if status_resp.json()["state"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.02)

    body = status_resp.json()
    assert body["state"] == "succeeded"
    assert body["result"] == {"processed": 5}


async def test_get_job_from_a_different_guild_returns_404() -> None:
    app, job_queue = _build_app()
    await job_queue.start()
    client = TestClient(app)
    _log_in(client)

    enqueue_resp = client.post(f"/api/guilds/{GUILD_ID}/jobs/bulk_action", json={})
    job_id = enqueue_resp.json()["job_id"]

    resp = client.get(f"/api/guilds/{OTHER_GUILD_ID}/jobs/{job_id}")

    assert resp.status_code == 404


async def test_get_unknown_job_returns_404() -> None:
    app, job_queue = _build_app()
    await job_queue.start()
    client = TestClient(app)
    _log_in(client)

    resp = client.get(f"/api/guilds/{GUILD_ID}/jobs/does-not-exist")

    assert resp.status_code == 404


async def test_jobs_api_requires_manage_guild_permission() -> None:
    app, job_queue = _build_app(manage_guild=False)
    await job_queue.start()
    client = TestClient(app)
    _log_in(client)

    resp = client.post(f"/api/guilds/{GUILD_ID}/jobs/bulk_action", json={})

    assert resp.status_code == 403


async def test_jobs_api_requires_authentication() -> None:
    app, job_queue = _build_app()
    await job_queue.start()
    client = TestClient(app)

    resp = client.post(f"/api/guilds/{GUILD_ID}/jobs/bulk_action", json={})

    assert resp.status_code == 401
