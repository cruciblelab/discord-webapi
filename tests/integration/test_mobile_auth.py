from urllib.parse import parse_qs, urlparse

import httpx
import respx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.auth import DiscordAuth

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"


def _make_app(
    *, mobile_redirect_uri: str | None = "myapp://auth-callback"
) -> tuple[FastAPI, DiscordAuth]:
    app = FastAPI()
    auth = DiscordAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
        mobile_redirect_uri=mobile_redirect_uri,
    )
    auth.install(app)
    return app, auth


def _mock_discord_endpoints(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-token-1",
                "refresh_token": "refresh-token-1",
                "expires_in": 604800,
                "token_type": "Bearer",
            },
        )
    )
    respx_mock.get(ME_URL).mock(
        return_value=httpx.Response(200, json={"id": "123456789", "username": "tester"})
    )
    respx_mock.get(GUILDS_URL).mock(return_value=httpx.Response(200, json=[]))


def _login_mobile_and_get_state(client: TestClient) -> str:
    login_resp = client.get("/auth/discord/login?mobile=true", follow_redirects=False)
    assert login_resp.status_code == 302
    location = login_resp.headers["location"]
    return parse_qs(urlparse(location).query)["state"][0]


def test_mobile_login_without_configured_redirect_uri_is_rejected() -> None:
    app, _auth = _make_app(mobile_redirect_uri=None)
    client = TestClient(app)

    resp = client.get("/auth/discord/login?mobile=true", follow_redirects=False)

    assert resp.status_code == 400


@respx.mock
def test_mobile_callback_redirects_with_session_id_and_sets_no_cookie() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    state = _login_mobile_and_get_state(client)
    _mock_discord_endpoints(respx.mock)

    callback_resp = client.get(
        f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False
    )

    assert callback_resp.status_code == 302
    location = callback_resp.headers["location"]
    assert location.startswith("myapp://auth-callback?")
    assert "dwa_session" not in client.cookies

    session_id = parse_qs(urlparse(location).query)["session_id"][0]
    assert session_id


@respx.mock
def test_bearer_token_from_mobile_flow_authenticates_requests() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    state = _login_mobile_and_get_state(client)
    _mock_discord_endpoints(respx.mock)
    callback_resp = client.get(
        f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False
    )
    session_id = parse_qs(urlparse(callback_resp.headers["location"]).query)["session_id"][0]

    me_resp = client.get(
        "/auth/discord/me", headers={"Authorization": f"Bearer {session_id}"}
    )

    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "tester"


@respx.mock
def test_bearer_token_also_works_for_a_cookie_based_login() -> None:
    """The same session_id authenticates via cookie or bearer header
    regardless of which flow created it — mobile apps, SaaS backends, or
    any other API client can use Bearer even against a dashboard that
    normally logs users in via cookie."""
    app, _auth = _make_app(mobile_redirect_uri=None)
    client = TestClient(app)
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    _mock_discord_endpoints(respx.mock)
    client.get(f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False)
    session_id = client.cookies["dwa_session"]

    fresh_client = TestClient(app)  # no cookies, only the bearer header
    resp = fresh_client.get(
        "/auth/discord/me", headers={"Authorization": f"Bearer {session_id}"}
    )

    assert resp.status_code == 200
    assert resp.json()["username"] == "tester"


@respx.mock
def test_bearer_token_logout_revokes_session() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    state = _login_mobile_and_get_state(client)
    _mock_discord_endpoints(respx.mock)
    callback_resp = client.get(
        f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False
    )
    session_id = parse_qs(urlparse(callback_resp.headers["location"]).query)["session_id"][0]
    headers = {"Authorization": f"Bearer {session_id}"}

    logout_resp = client.post("/auth/discord/logout", headers=headers)
    assert logout_resp.status_code == 204

    me_resp = client.get("/auth/discord/me", headers=headers)
    assert me_resp.status_code == 401


def test_missing_bearer_and_cookie_returns_401() -> None:
    app, _auth = _make_app()
    client = TestClient(app)

    resp = client.get("/auth/discord/me", headers={"Authorization": "Bearer not-a-real-session"})

    assert resp.status_code == 401
