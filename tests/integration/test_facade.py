from urllib.parse import parse_qs, urlparse

import discord
import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from discord.ext import commands as dpy_commands
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi import DiscordAuth, DiscordWebAPI, InProcessTransport
from discord_webapi.jobs import InProcessJobQueue

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"


def _build_bot() -> dpy_commands.Bot:
    bot = dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )

    @bot.hybrid_command(name="ping", description="Ping the bot")
    async def ping(ctx: dpy_commands.Context) -> None:
        ...

    return bot


def _build_app() -> tuple[FastAPI, DiscordWebAPI]:
    app = FastAPI()
    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    # sync_commands=False: this test simulates on_ready without a real
    # Gateway connection, so the bot never gets an application_id -- a
    # real bot always has one by the time on_ready fires, but faking that
    # here isn't what this test is about (see test_quickstart.py /
    # test_command_cooldown.py for real command-sync-adjacent coverage).
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth, sync_commands=False)
    api.install(app)
    return app, api


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


async def test_facade_wires_auth_and_commands_routes() -> None:
    app, api = _build_app()
    await api._on_ready()  # simulates the bot's on_ready firing

    async def handle_get_member(payload: dict) -> dict:
        return {"found": True, "role_ids": [], "permissions": discord.Permissions.all().value}

    api.transport._handlers.pop("get_member", None)
    api.transport.register_handler("get_member", handle_get_member)

    client = TestClient(app)
    _log_in(client)

    resp = client.get("/api/guilds/123/commands")

    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "ping" in names


async def test_facade_registers_member_lookup_handler() -> None:
    _app, api = _build_app()

    response = await api.transport.request("get_member", {"guild_id": 1, "user_id": 2})

    assert response == {"found": False}


async def test_on_ready_syncs_commands_globally_by_default() -> None:
    """discord.py never pushes slash commands to Discord on its own --
    without this, /commands never show up in Discord's UI at all, no
    error, no warning, just silence. This is the regression test for
    that trap."""
    from unittest.mock import AsyncMock

    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth)
    bot.tree.sync = AsyncMock()  # type: ignore[method-assign]

    await api._on_ready()

    bot.tree.sync.assert_awaited_once_with()


async def test_on_ready_syncs_to_a_single_guild_when_configured() -> None:
    from unittest.mock import AsyncMock, MagicMock

    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth, sync_guild_id=999)
    bot.tree.sync = AsyncMock()  # type: ignore[method-assign]
    bot.tree.copy_global_to = MagicMock()  # type: ignore[method-assign]

    await api._on_ready()

    bot.tree.copy_global_to.assert_called_once()
    bot.tree.sync.assert_awaited_once()
    _, kwargs = bot.tree.sync.call_args
    assert kwargs["guild"].id == 999


async def test_on_ready_never_syncs_when_disabled() -> None:
    from unittest.mock import AsyncMock

    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth, sync_commands=False)
    bot.tree.sync = AsyncMock()  # type: ignore[method-assign]

    await api._on_ready()

    bot.tree.sync.assert_not_awaited()


async def test_on_ready_only_syncs_once_across_multiple_calls() -> None:
    """`on_ready` can fire more than once (Gateway reconnects) -- syncing
    every single time would be wasteful and risks rate limits."""
    from unittest.mock import AsyncMock

    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth)
    bot.tree.sync = AsyncMock()  # type: ignore[method-assign]

    await api._on_ready()
    await api._on_ready()

    bot.tree.sync.assert_awaited_once_with()


async def test_install_enable_jobs_without_job_queue_raises() -> None:
    transport = InProcessTransport()
    bot = _build_bot()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    api = DiscordWebAPI(bot=bot, transport=transport, auth=auth, sync_commands=False)

    with pytest.raises(RuntimeError, match="job_queue"):
        api.install(FastAPI(), enable_jobs=True)

    # sanity: passing a queue actually works (fresh bot/transport -- the
    # ones above already registered handlers on `transport`, and
    # InProcessTransport allows exactly one handler per command)
    api2 = DiscordWebAPI(
        bot=_build_bot(),
        transport=InProcessTransport(),
        auth=auth,
        job_queue=InProcessJobQueue(),
        sync_commands=False,
    )
    api2.install(FastAPI(), enable_jobs=True)


async def test_for_bot_process_accepts_a_job_queue() -> None:
    """A job handler that needs live bot/Gateway access must run in the
    bot process -- for_bot_process() needs to accept job_queue=... for
    that (it's not just a for_web_process()-only concern)."""
    job_queue = InProcessJobQueue()

    async def handle_bulk_dm(payload: dict) -> dict:
        return {"sent": 0}

    job_queue.register_worker("bulk_dm", handle_bulk_dm)

    api = DiscordWebAPI.for_bot_process(
        bot=_build_bot(),
        transport=InProcessTransport(),
        job_queue=job_queue,
        sync_commands=False,
    )

    assert api.job_queue is job_queue


async def test_lifespan_stops_job_queue_only_if_it_actually_started() -> None:
    """If job_queue.start() itself raises, stop() must not be called on a
    queue that never started (would otherwise be a latent resource-state
    bug the moment start() grows any fallible step)."""
    from unittest.mock import AsyncMock

    from discord_webapi import _with_job_queue

    job_queue = InProcessJobQueue()
    job_queue.start = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    job_queue.stop = AsyncMock()  # type: ignore[method-assign]

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_inner():
        yield

    with pytest.raises(RuntimeError, match="boom"):
        async with _with_job_queue(noop_inner(), job_queue):
            pass

    job_queue.stop.assert_not_awaited()
