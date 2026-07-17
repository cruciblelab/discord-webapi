"""A standalone, clickable test page for every `discord_webapi.captcha`
piece -- no Discord bot, no OAuth, nothing but this library's captcha
subsystem. Point a browser at it, click through every provider and the
invisible/behavioral layer, and read the pass/fail log on screen.

What's on the page (`/playground`):
    - The bundled, ready-made widget (`discord_webapi.captcha.widget`) --
      the "fast path" for consumers who just want a drop-in checkbox
      rather than building their own frontend against the raw endpoints.
      A dropdown picks which `CaptchaGate` configuration it talks to
      (behavior-only, Math, Text, PoW, Path-Trace, ...) so the *same*
      widget script is shown adapting its own UI to whatever the gate
      issues -- that's the actual product, not a playground-only mock.
    - Every self-hosted provider available individually too (Math, Text --
      need Pillow, `discord-webapi[captcha]`; Proof-of-Work; Path-Trace),
      for anyone who wants to see the raw `build_captcha_router()`
      endpoints without the widget in the way.
    - reCAPTCHA / hCaptcha -- only rendered if you set real site keys via
      env vars (see below); otherwise the page says so plainly instead of
      pretending to test something it can't.
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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from discord_webapi.captcha.api import build_captcha_router
from discord_webapi.captcha.base import CaptchaProvider
from discord_webapi.captcha.checks import VerificationCheck, VerificationContext
from discord_webapi.captcha.gate import CaptchaGate
from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
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
from discord_webapi.captcha.widget import build_captcha_widget_router
from discord_webapi.transport import InProcessTransport

app = FastAPI(title="discord-webapi captcha playground")

# -- every self-hosted provider, all sharing one store -----------------
_captcha_store = MemoryCaptchaStore()
providers: dict[str, CaptchaProvider] = {
    "math": MathCaptchaProvider(_captcha_store),
    "text": TextCaptchaProvider(_captcha_store),
    "pow": ProofOfWorkProvider(_captcha_store, difficulty=18),
    # tolerance is bumped above the library default (24px) for this demo
    # specifically -- a real finger on a phone screen is much less precise
    # than a mouse cursor, and 24px turned out to be uncomfortably tight
    # for touch during manual testing. This is a playground-only tuning
    # choice, not a change to PathTraceProvider's own default.
    "path-trace": PathTraceProvider(_captcha_store, tolerance=34.0),
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

# -- the bundled widget, dogfooded here: one CaptchaGate per demo
# configuration, all sharing the same behavior-layer extra_checks above so
# the widget's UI is the only thing that changes as you switch kind. No
# Discord OAuth in this standalone demo, so require_account stays False
# throughout and every verification is minted for a fake user_id=0.
_transport = InProcessTransport()
_gates: dict[str, CaptchaGate] = {
    "none": CaptchaGate(
        _transport, MemoryVerificationStore(), require_captcha=False, extra_checks=behavior_checks
    ),
}
for _kind, _provider in providers.items():
    _gates[_kind] = CaptchaGate(
        _transport, MemoryVerificationStore(), _provider, extra_checks=behavior_checks
    )


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
    widget_gate_kinds: list[str]
    recaptcha_site_key: str | None = None
    hcaptcha_site_key: str | None = None


@app.get("/api/playground/config")
async def playground_config() -> PlaygroundConfig:
    return PlaygroundConfig(
        available_kinds=list(providers.keys()),
        widget_gate_kinds=list(_gates.keys()),
        recaptcha_site_key=_recaptcha_site_key,
        hcaptcha_site_key=_hcaptcha_site_key,
    )


class WidgetTokenResponse(BaseModel):
    token: str


@app.get("/api/playground/widget-token")
async def widget_token(kind: str = "none") -> WidgetTokenResponse:
    """Mints a fresh one-time verification token for the widget to attach
    to -- stands in for whatever your bot command would normally do
    (`gate.create_verification(user_id=..., purpose=...)`) since this demo
    has no real Discord user to bind one to.

    `build_captcha_router()`'s `/api/captcha/gate/{token}` endpoints read a
    single `app.state.discord_webapi_captcha_gate` -- a real deployment
    has exactly one gate for its one integration, so that's the right
    design there. This demo instead lets you switch between several gate
    configurations from one page, so it swaps which gate is "active" at
    the moment a token is minted. Fine for a single-operator local demo;
    don't do this in a real multi-user deployment (pick one gate).
    """
    gate = _gates.get(kind)
    if gate is None:
        raise HTTPException(404, f"no demo gate configured for kind={kind!r}")
    app.state.discord_webapi_captcha_gate = gate
    request = await gate.create_verification(user_id=0, purpose="playground-widget-demo")
    return WidgetTokenResponse(token=request.token)


app.include_router(build_captcha_widget_router())

_PLAYGROUND_HTML = Path(__file__).parent / "playground.html"


@app.get("/playground")
async def playground() -> FileResponse:
    return FileResponse(_PLAYGROUND_HTML)
