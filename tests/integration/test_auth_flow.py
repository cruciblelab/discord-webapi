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


def _make_app() -> tuple[FastAPI, DiscordAuth]:
    app = FastAPI()
    auth = DiscordAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
        login_success_redirect="/dashboard",
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
        return_value=httpx.Response(
            200,
            json={"id": "123456789", "username": "tester", "global_name": "Tester", "avatar": None},
        )
    )
    respx_mock.get(GUILDS_URL).mock(
        return_value=httpx.Response(200, json=[{"id": "111"}, {"id": "222"}])
    )


def _login_and_get_state(client: TestClient) -> str:
    login_resp = client.get("/auth/discord/login", follow_redirects=False)
    assert login_resp.status_code == 302
    location = login_resp.headers["location"]
    return parse_qs(urlparse(location).query)["state"][0]


@respx.mock
def test_full_login_flow_sets_session_and_exposes_user() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    state = _login_and_get_state(client)
    _mock_discord_endpoints(respx.mock)

    callback_resp = client.get(
        f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False
    )

    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == "/dashboard"
    assert "dwa_session" in client.cookies

    me_resp = client.get("/auth/discord/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["id"] == 123456789
    assert body["username"] == "tester"
    assert body["guild_ids"] == [111, 222]


@respx.mock
def test_callback_with_mismatched_state_is_rejected() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    _login_and_get_state(client)

    resp = client.get(
        "/auth/discord/callback?code=some-code&state=not-the-real-state", follow_redirects=False
    )

    assert resp.status_code == 400
    assert "dwa_session" not in client.cookies


@respx.mock
def test_callback_without_state_cookie_is_rejected() -> None:
    app, _auth = _make_app()
    client = TestClient(app)

    resp = client.get(
        "/auth/discord/callback?code=some-code&state=whatever", follow_redirects=False
    )

    assert resp.status_code == 400


def test_me_without_session_returns_401() -> None:
    app, _auth = _make_app()
    client = TestClient(app)

    resp = client.get("/auth/discord/me")

    assert resp.status_code == 401


@respx.mock
def test_logout_clears_session() -> None:
    app, _auth = _make_app()
    client = TestClient(app)
    state = _login_and_get_state(client)
    _mock_discord_endpoints(respx.mock)
    client.get(f"/auth/discord/callback?code=some-code&state={state}", follow_redirects=False)

    logout_resp = client.post("/auth/discord/logout")

    assert logout_resp.status_code == 204
    me_resp = client.get("/auth/discord/me")
    assert me_resp.status_code == 401
