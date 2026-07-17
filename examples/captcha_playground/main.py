"""A standalone, clickable test page for every `discord_webapi.captcha`
piece -- no Discord bot, no OAuth, nothing but this library's captcha
subsystem. Point a browser at it, click through every provider and the
invisible/behavioral layer, and read the pass/fail log on screen.

What's on the page (`/playground`):
    - Every self-hosted provider: Math, Text (need Pillow --
      `discord-webapi[captcha]`), Proof-of-Work (real hashcash search done
      in the page's own JS via `crypto.subtle.digest`), Path-Trace (draws
      a line on a <canvas>, captures your actual pointer path).
    - reCAPTCHA / hCaptcha widgets -- only rendered if you set real site
      keys via env vars (see below); otherwise the page says so plainly
      instead of pretending to test something it can't.
    - The invisible layer: `SignalScoreCheck` (all default heuristics,
      including the mouse-kinematics and homing-correction ones),
      `reject_webdriver`/`require_min_interaction_ms`, and
      `RepeatedMovementCheck` (hit "resend the same movement" to watch it
      flip from pass to fail on the second submission -- that's the
      replay-detection check catching itself).

Every check's real pass/fail + detail string is logged to an on-screen
panel (and a "copy log" button), so results can be captured and shared
without anyone needing to read server logs.

Run:
    pip install -e ".[captcha]"                 # Pillow, for Math/Text
    # optional, only if you want to also test the 3rd-party widgets:
    export RECAPTCHA_SITE_KEY=...  RECAPTCHA_SECRET_KEY=...
    export HCAPTCHA_SITE_KEY=...   HCAPTCHA_SECRET_KEY=...
    uvicorn main:app --reload --app-dir examples/captcha_playground

Then open http://localhost:8000/playground .
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from discord_webapi.captcha.api import build_captcha_router
from discord_webapi.captcha.base import CaptchaProvider
from discord_webapi.captcha.checks import VerificationCheck, VerificationContext
from discord_webapi.captcha.memory import MemoryCaptchaStore
from discord_webapi.captcha.models import VerificationRequest
from discord_webapi.captcha.providers.math_captcha import MathCaptchaProvider
from discord_webapi.captcha.providers.path_trace import PathTraceProvider
from discord_webapi.captcha.providers.proof_of_work import ProofOfWorkProvider
from discord_webapi.captcha.providers.text_captcha import TextCaptchaProvider
from discord_webapi.captcha.replay_guard import (
    MemoryTrajectoryFingerprintStore,
    RepeatedMovementCheck,
)
from discord_webapi.captcha.scoring import SignalScoreCheck
from discord_webapi.captcha.signals import reject_webdriver, require_min_interaction_ms

app = FastAPI(title="discord-webapi captcha playground")

# -- every self-hosted provider, all sharing one store -----------------
_captcha_store = MemoryCaptchaStore()
providers: dict[str, CaptchaProvider] = {
    "math": MathCaptchaProvider(_captcha_store),
    "text": TextCaptchaProvider(_captcha_store),
    "pow": ProofOfWorkProvider(_captcha_store, difficulty=18),
    "path-trace": PathTraceProvider(_captcha_store),
}

_recaptcha_site_key = os.environ.get("RECAPTCHA_SITE_KEY")
_recaptcha_secret_key = os.environ.get("RECAPTCHA_SECRET_KEY")
if _recaptcha_site_key and _recaptcha_secret_key:
    from discord_webapi.captcha.providers.recaptcha import ReCaptchaProvider

    providers["recaptcha"] = ReCaptchaProvider(
        site_key=_recaptcha_site_key, secret_key=_recaptcha_secret_key
    )

_hcaptcha_site_key = os.environ.get("HCAPTCHA_SITE_KEY")
_hcaptcha_secret_key = os.environ.get("HCAPTCHA_SECRET_KEY")
if _hcaptcha_site_key and _hcaptcha_secret_key:
    from discord_webapi.captcha.providers.hcaptcha import HCaptchaProvider

    providers["hcaptcha"] = HCaptchaProvider(
        site_key=_hcaptcha_site_key, secret_key=_hcaptcha_secret_key
    )

app.state.discord_webapi_captcha_providers = providers
app.include_router(build_captcha_router())

# -- the invisible/behavioral layer, run directly (no CaptchaGate/token
# needed for a stateless playground -- each check is exercised exactly as
# CaptchaGate would run it, just without the bot-verification-link
# plumbing around it) --
_fingerprint_store = MemoryTrajectoryFingerprintStore()
behavior_checks: list[VerificationCheck] = [
    reject_webdriver(),
    require_min_interaction_ms(400),
    SignalScoreCheck(threshold=0.6),
    RepeatedMovementCheck(_fingerprint_store),
]


class BehaviorCheckRequest(BaseModel):
    signals: dict[str, Any] = {}


class CheckResultOut(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class BehaviorCheckResponse(BaseModel):
    overall_passed: bool
    results: list[CheckResultOut]


@app.post("/api/playground/behavior-check")
async def behavior_check(body: BehaviorCheckRequest) -> BehaviorCheckResponse:
    now = datetime.now(UTC)
    dummy_request = VerificationRequest(
        token="playground",
        user_id=0,
        purpose="playground-test",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    ctx = VerificationContext(request=dummy_request, signals=body.signals)
    results = []
    overall = True
    for check in behavior_checks:
        outcome = await check.run(ctx)
        results.append(
            CheckResultOut(name=check.name, passed=outcome.passed, detail=outcome.detail)
        )
        overall = overall and outcome.passed
    return BehaviorCheckResponse(overall_passed=overall, results=results)


class PlaygroundConfig(BaseModel):
    available_kinds: list[str]
    recaptcha_site_key: str | None = None
    hcaptcha_site_key: str | None = None


@app.get("/api/playground/config")
async def playground_config() -> PlaygroundConfig:
    return PlaygroundConfig(
        available_kinds=list(providers.keys()),
        recaptcha_site_key=_recaptcha_site_key,
        hcaptcha_site_key=_hcaptcha_site_key,
    )


_PLAYGROUND_HTML = Path(__file__).parent / "playground.html"


@app.get("/playground")
async def playground() -> FileResponse:
    return FileResponse(_PLAYGROUND_HTML)
