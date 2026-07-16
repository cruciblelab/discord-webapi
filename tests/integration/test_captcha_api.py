"""Exercises build_captcha_router() end to end via FastAPI's TestClient --
both the plain web-usage endpoints (no auth, no Discord user involved) and
the bot-gated verification endpoints (the giveaway-bot scenario).
"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.captcha import (
    CaptchaGate,
    MathCaptchaProvider,
    MemoryCaptchaStore,
    MemoryVerificationStore,
    build_captcha_router,
)
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.transport import InProcessTransport


def _build_app(
    *, verify_rate_limiter: TokenBucketLimiter | None = None
) -> tuple[FastAPI, CaptchaGate]:
    app = FastAPI()
    transport = InProcessTransport()
    provider = MathCaptchaProvider(MemoryCaptchaStore())
    gate = CaptchaGate(transport, MemoryVerificationStore(), provider)

    app.state.discord_webapi_captcha_providers = {"math": provider}
    app.state.discord_webapi_captcha_gate = gate
    app.include_router(build_captcha_router(verify_rate_limiter=verify_rate_limiter))
    return app, gate


# -- plain web usage --


def test_create_challenge_returns_a_renderable_image() -> None:
    app, _gate = _build_app()
    with TestClient(app) as client:
        resp = client.get("/api/captcha/challenge", params={"kind": "math"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["kind"] == "math"
        assert body["image_data_uri"].startswith("data:image/png;base64,")


def test_create_challenge_for_an_unregistered_kind_is_404() -> None:
    app, _gate = _build_app()
    with TestClient(app) as client:
        resp = client.get("/api/captcha/challenge", params={"kind": "not-registered"})

        assert resp.status_code == 404


def test_verify_challenge_round_trip() -> None:
    app, gate = _build_app()
    with TestClient(app) as client:
        challenge_resp = client.get("/api/captcha/challenge", params={"kind": "math"})
        challenge_id = challenge_resp.json()["challenge_id"]

        provider: MathCaptchaProvider = gate.provider  # type: ignore[assignment]
        # the test drives the browser side of a real flow -- reads the
        # correct answer server-side the same way inspecting the rendered
        # image with your own eyes would, rather than reaching into
        # rendering internals.
        pending = asyncio.run(provider.store.get(challenge_id))
        assert pending is not None

        verify_resp = client.post(
            "/api/captcha/verify",
            json={"kind": "math", "challenge_id": challenge_id, "response": pending.answer},
        )

        assert verify_resp.status_code == 200
        assert verify_resp.json() == {"verified": True}


def test_verify_challenge_with_a_wrong_answer() -> None:
    app, _gate = _build_app()
    with TestClient(app) as client:
        challenge_resp = client.get("/api/captcha/challenge", params={"kind": "math"})
        challenge_id = challenge_resp.json()["challenge_id"]

        verify_resp = client.post(
            "/api/captcha/verify",
            json={"kind": "math", "challenge_id": challenge_id, "response": "definitely-wrong"},
        )

        assert verify_resp.json() == {"verified": False}


def test_verify_rate_limit_returns_429_when_exceeded() -> None:
    app, _gate = _build_app(verify_rate_limiter=TokenBucketLimiter(1, 60.0))
    with TestClient(app) as client:
        first = client.post(
            "/api/captcha/verify", json={"kind": "math", "challenge_id": "x", "response": "y"}
        )
        second = client.post(
            "/api/captcha/verify", json={"kind": "math", "challenge_id": "x", "response": "y"}
        )

        assert first.status_code == 200
        assert second.status_code == 429


# -- bot-gated verification (the giveaway-bot scenario) --


def test_gate_get_challenge_renders_the_verification_links_challenge() -> None:
    app, gate = _build_app()
    with TestClient(app) as client:
        request = asyncio.run(
            gate.create_verification(user_id=100, guild_id=999, purpose="giveaway_entry")
        )

        resp = client.get(f"/api/captcha/gate/{request.token}")

        assert resp.status_code == 200
        assert resp.json()["challenge_id"] == request.challenge.challenge_id


def test_gate_get_challenge_of_unknown_token_is_404() -> None:
    app, _gate = _build_app()
    with TestClient(app) as client:
        resp = client.get("/api/captcha/gate/never-issued")

        assert resp.status_code == 404


def test_gate_verify_solves_the_giveaway_scenario() -> None:
    """End to end: create a verification link (what a giveaway bot's
    /join command would do), fetch its challenge (what the web page the
    bot's link points to would do), solve it, confirm success."""
    app, gate = _build_app()
    with TestClient(app) as client:
        request = asyncio.run(
            gate.create_verification(
                user_id=100,
                guild_id=999,
                purpose="giveaway_entry",
                metadata={"giveaway_id": "spring-giveaway"},
            )
        )
        provider: MathCaptchaProvider = gate.provider  # type: ignore[assignment]
        pending = asyncio.run(provider.store.get(request.challenge.challenge_id))
        assert pending is not None

        verify_resp = client.post(
            f"/api/captcha/gate/{request.token}/verify", json={"response": pending.answer}
        )

        assert verify_resp.status_code == 200
        assert verify_resp.json() == {"verified": True}

        # the link is now spent -- re-fetching its challenge has nothing to show
        followup = client.get(f"/api/captcha/gate/{request.token}")
        assert followup.status_code == 404


def test_gate_verify_of_unknown_token_returns_not_verified() -> None:
    app, _gate = _build_app()
    with TestClient(app) as client:
        resp = client.post("/api/captcha/gate/never-issued/verify", json={"response": "anything"})

        assert resp.status_code == 200
        assert resp.json() == {"verified": False}


def test_captcha_router_without_a_gate_configured_returns_404_for_gate_routes() -> None:
    app = FastAPI()
    provider = MathCaptchaProvider(MemoryCaptchaStore())
    app.state.discord_webapi_captcha_providers = {"math": provider}
    app.include_router(build_captcha_router())

    with TestClient(app) as client:
        resp = client.get("/api/captcha/gate/whatever")

        assert resp.status_code == 404
