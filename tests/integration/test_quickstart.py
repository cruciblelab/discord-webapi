from pathlib import Path

from discord.ext import commands as dpy_commands
from fastapi.testclient import TestClient

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents


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
