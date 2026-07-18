"""`discord_webapi.captcha` is now a thin re-export of the standalone
`webapi_captcha` package plus two small Discord-specific additions
(`resolve_discord_user_id`, `build_discord_captcha_router`) -- this
covers that the re-export surface is intact and that the two additions
actually wire an account-only gate to a real signed-in Discord user via
this library's own OAuth login (the scenario `webapi_captcha`'s own test
suite can't cover, since it knows nothing about Discord)."""

from urllib.parse import parse_qs, urlparse

import httpx
import respx
import webapi_captcha
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

import discord_webapi.captcha as captcha_shim
from discord_webapi.auth import DiscordAuth
from discord_webapi.transport import InProcessTransport

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
ME_URL = "https://discord.com/api/v10/users/@me"
GUILDS_URL = "https://discord.com/api/v10/users/@me/guilds"


def test_shim_reexports_every_public_webapi_captcha_name() -> None:
    for name in captcha_shim.__all__:
        if name in ("build_discord_captcha_router", "resolve_discord_user_id"):
            continue  # discord_webapi's own additions, not re-exports
        assert hasattr(captcha_shim, name), f"discord_webapi.captcha is missing {name!r}"
        assert getattr(captcha_shim, name) is getattr(webapi_captcha, name)


def _build_account_app() -> tuple[FastAPI, "webapi_captcha.CaptchaGate"]:
    app = FastAPI()
    transport = InProcessTransport()
    gate = webapi_captcha.CaptchaGate(
        transport,
        webapi_captcha.MemoryVerificationStore(),
        require_captcha=False,
        require_account=True,
    )
    auth = DiscordAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )
    auth.install(app)
    # No current_user_id_resolver passed -- build_discord_captcha_router's
    # whole point is defaulting that to resolve_discord_user_id for us.
    app.include_router(captcha_shim.build_discord_captcha_router(gate=gate))
    return app, gate


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


def test_build_discord_captcha_router_binds_the_real_signed_in_discord_user() -> None:
    import asyncio

    app, gate = _build_account_app()
    with TestClient(app) as client:
        req_for_1 = asyncio.run(gate.create_verification(user_id=1, purpose="giveaway_entry"))

        # not logged in yet -> account check fails
        anon = client.post(f"/api/captcha/gate/{req_for_1.token}/verify", json={})
        assert anon.json()["verified"] is False
        assert anon.json()["failed_check"] == "account"

        _log_in(client)  # mocked login is Discord user id=1

        # a link for someone else still fails even while logged in
        req_for_other = asyncio.run(
            gate.create_verification(user_id=999, purpose="giveaway_entry")
        )
        wrong = client.post(f"/api/captcha/gate/{req_for_other.token}/verify", json={})
        assert wrong.json()["verified"] is False
        assert wrong.json()["failed_check"] == "account"

        # a link issued for the signed-in user passes -- with zero explicit
        # current_user_id_resolver wiring by the caller
        right = client.post(f"/api/captcha/gate/{req_for_1.token}/verify", json={})
        assert right.json()["verified"] is True


async def test_resolve_discord_user_id_maps_a_discord_user_to_its_id() -> None:
    from discord_webapi.auth.models import DiscordUser

    user = DiscordUser(id=42, username="someone")

    assert await captcha_shim.resolve_discord_user_id(user) == 42
    assert await captcha_shim.resolve_discord_user_id(None) is None
