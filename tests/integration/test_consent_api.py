from urllib.parse import parse_qs, urlparse

import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth
from discord_webapi.consent import build_consent_router
from discord_webapi.storage import MemoryConsentStore
from discord_webapi.web import build_default_dashboard_router

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"


def _build_app() -> FastAPI:
    app = FastAPI()
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)
    app.state.discord_webapi_consent_store = MemoryConsentStore()
    app.include_router(build_consent_router())
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


def test_consent_is_absent_until_given() -> None:
    app = _build_app()
    with TestClient(app) as client:
        _log_in(client)
        resp = client.get("/api/consent")
        assert resp.status_code == 200
        assert resp.json() is None


def test_giving_and_reading_back_consent() -> None:
    app = _build_app()
    with TestClient(app) as client:
        _log_in(client)

        post_resp = client.post("/api/consent", json={"consent_version": "2026-01-01"})
        assert post_resp.status_code == 200
        assert post_resp.json()["consent_version"] == "2026-01-01"
        assert post_resp.json()["user_id"] == 1

        get_resp = client.get("/api/consent")
        assert get_resp.json()["consent_version"] == "2026-01-01"


def test_consent_requires_authentication() -> None:
    app = _build_app()
    with TestClient(app) as client:
        resp = client.get("/api/consent")
        assert resp.status_code == 401


def test_dashboard_banner_and_consent_api_share_the_same_version() -> None:
    """The banner's `POST /api/consent` call must record a version that
    `GET /api/consent` (used to decide whether to show it again) actually
    matches -- exercised end to end, not just each endpoint in isolation.
    """
    app = _build_app()
    app.include_router(
        build_default_dashboard_router(
            enable_cookie_consent=True, cookie_consent_version="7"
        )
    )
    with TestClient(app) as client:
        _log_in(client)

        page = client.get("/")
        assert 'COOKIE_CONSENT_VERSION = "7"' in page.text

        client.post("/api/consent", json={"consent_version": "7"})

        get_resp = client.get("/api/consent")
        assert get_resp.json()["consent_version"] == "7"
