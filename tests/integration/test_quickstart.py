import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from discord.ext import commands as dpy_commands
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents
from discord_webapi.storage.base import Session
from discord_webapi.storage.sql import Base
from discord_webapi.storage.sql import create_all as create_all_tables

POSTGRES_URL = os.environ.get(
    "DWA_TEST_POSTGRES_URL", "postgresql+asyncpg://dwa_test:dwa_test@localhost/dwa_test"
)


def _build_bot() -> dpy_commands.Bot:
    bot = dpy_commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)

    @bot.hybrid_command(name="ping", description="Replies with pong")
    async def ping(ctx: dpy_commands.Context) -> None:
        ...

    return bot


def test_default_intents_enables_members() -> None:
    intents = default_intents()

    assert intents.members is True
    assert intents.guilds is True  # still has the Intents.default() baseline


def test_default_intents_enables_message_content() -> None:
    """Without this, prefix/hybrid commands (`!ping`) never fire --
    discord.py can't read a message's text to match it against
    `command_prefix`, so the bot silently never responds, no error."""
    intents = default_intents()

    assert intents.message_content is True


def test_quickstart_builds_a_working_app(tmp_path: Path) -> None:
    bot = _build_bot()

    app = DiscordWebAPI.quickstart(
        bot=bot,
        bot_token="fake-token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        fernet_key="zH4uqykSk91xLINmy-VyO7NlFCUj-TDNvJXPjaFXwCg=",
        db_path=tmp_path / "test-dashboard.sqlite3",
    )

    client = TestClient(app)

    # Dashboard is bundled and mounted by default.
    dashboard_resp = client.get("/dashboard")
    assert dashboard_resp.status_code == 200
    assert "discord-webapi" in dashboard_resp.text

    # Auth routes came from the wired-up DiscordAuth.
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    assert login_resp.status_code == 302

    # Unauthenticated -> 401, proving the commands router is mounted too.
    commands_resp = client.get("/api/guilds/123/commands")
    assert commands_resp.status_code == 401


def test_quickstart_can_disable_the_bundled_dashboard(tmp_path: Path) -> None:
    bot = _build_bot()

    app = DiscordWebAPI.quickstart(
        bot=bot,
        bot_token="fake-token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        fernet_key="zH4uqykSk91xLINmy-VyO7NlFCUj-TDNvJXPjaFXwCg=",
        db_path=tmp_path / "test-dashboard-2.sqlite3",
        serve_dashboard=False,
    )

    client = TestClient(app)

    assert client.get("/dashboard").status_code == 404


async def _postgres_reachable() -> bool:
    engine = create_async_engine(POSTGRES_URL)
    try:
        async with engine.begin():
            return True
    except SQLAlchemyError:
        return False
    finally:
        await engine.dispose()


async def test_quickstart_database_url_wires_up_postgres() -> None:
    """Confirms `database_url` really does route quickstart()'s storage to
    Postgres, not just SQLite. Talks directly to the exact store objects
    `quickstart()` constructs (SQLSessionStore/SQLCommandConfigStore/
    SQLAuthzStore against the given URL) rather than round-tripping through
    TestClient -- Starlette's TestClient spins up a fresh event loop per
    request when not used as `with TestClient(...) as client:`, and asyncpg
    connections are pinned to the loop that created them, so two separate
    un-with'd requests that both touch the DB fail with "attached to a
    different loop" regardless of whether discord-webapi's own code is
    correct. Using `with` instead would require the bundled lifespan to
    actually log the bot into Discord, which is a separate concern from
    what this test is about.
    """
    if not await _postgres_reachable():
        pytest.skip(f"No Postgres reachable at {POSTGRES_URL} (set DWA_TEST_POSTGRES_URL)")

    bot = _build_bot()
    app = DiscordWebAPI.quickstart(
        bot=bot,
        bot_token="fake-token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        fernet_key="zH4uqykSk91xLINmy-VyO7NlFCUj-TDNvJXPjaFXwCg=",
        database_url=POSTGRES_URL,
    )

    auth = app.state.discord_webapi_auth
    from discord_webapi.storage.sql import SQLSessionStore

    assert isinstance(auth.session_store, SQLSessionStore)

    engine = auth.session_store._engine
    assert str(engine.url).startswith("postgresql+asyncpg://")

    await create_all_tables(engine)
    try:
        now = datetime.now(UTC)
        session = Session(
            session_id="quickstart-pg-session",
            user_id=1,
            username="tester",
            created_at=now,
            expires_at=now + timedelta(days=30),
            encrypted_access_token=b"a",
            encrypted_refresh_token=b"b",
            discord_token_expires_at=now + timedelta(minutes=10),
        )
        await auth.session_store.create(session)
        fetched = await auth.session_store.get(session.session_id)
        assert fetched == session
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
