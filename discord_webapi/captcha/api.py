"""Dashboard-facing captcha API -- two independent uses:

- **Plain web usage** (`/api/captcha/challenge`, `/api/captcha/verify`):
  protect any point on your own site (a signup form, a comment box, ...)
  with whichever registered provider you name by `kind` -- no Discord
  user/guild involved at all.
- **Bot-gated verification** (`/api/captcha/gate/{token}`): the other half
  of `discord_webapi.captcha.gate.CaptchaGate` -- serves and resolves a
  token a bot handed a specific user (see that module's docstring for the
  giveaway-bot scenario and the account-only / captcha / "safety" /
  click-only modes).

Neither is wired into `DiscordWebAPI.install()` automatically: unlike
audit/consent/ratelimits, there's no sensible default *provider* to fall
back to (which captcha backend, whose reCAPTCHA keys?), so mount this
yourself once you've picked and constructed one:

    app.state.discord_webapi_captcha_providers = {"math": math_provider}
    app.state.discord_webapi_captcha_gate = gate  # optional, only if you use CaptchaGate
    app.include_router(build_captcha_router())

The gate's account-check (`require_account=True`) reads the signed-in
Discord user from the same OAuth session the rest of the library uses, so
`DiscordAuth.install(app)` must have run for that mode to have anyone to
match against. Captcha-only / click-only gates work without it.

**More than one `CaptchaGate` purpose at once** (e.g. a giveaway-entry
gate and a separate "verify before appealing a ban" gate)? Pass `gate=`
explicitly and mount the router once per gate under different prefixes
instead of relying on the single `app.state.discord_webapi_captcha_gate`:

    app.include_router(build_captcha_router(gate=giveaway_gate), prefix="/giveaway")
    app.include_router(build_captcha_router(gate=appeal_gate), prefix="/appeal")

Each mount gets its own `/{prefix}/api/captcha/gate/{token}` pair, fully
independent. Point the bundled widget's `data-api-base` at the matching
prefix (empty string, the default, means unprefixed -- the single-gate
case above). The plain `/challenge`+`/verify` provider endpoints get
duplicated harmlessly under each prefix; mount the router without a
`gate=` (or without a `prefix`) once more if you only want one
unprefixed copy of those for direct site usage.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from discord_webapi.auth.dependencies import get_current_user_optional
from discord_webapi.auth.models import DiscordUser
from discord_webapi.captcha.base import CaptchaProvider
from discord_webapi.captcha.gate import CaptchaGate
from discord_webapi.captcha.models import CaptchaChallenge
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter

_DEFAULT_VERIFY_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


class CaptchaVerifyRequest(BaseModel):
    kind: str
    challenge_id: str
    response: str


class GateVerifyRequest(BaseModel):
    captcha_response: str | None = None
    # Arbitrary client-submitted signals for your own extra_checks
    # (fingerprint token, behavioral data, ...). Untrusted -- your check
    # decides how much to believe them.
    signals: dict[str, Any] = {}


class CaptchaVerifyResult(BaseModel):
    verified: bool


class GateVerifyResult(BaseModel):
    verified: bool
    # Which check blocked it (e.g. "account" -> the frontend can prompt
    # "sign in with Discord first"; "captcha" -> "wrong answer"). None on
    # success.
    failed_check: str | None = None
    detail: str | None = None


class GateInfo(BaseModel):
    """What the frontend needs to render the right thing for a gate link:
    the captcha image if there is one, plus whether the visitor has to be
    signed in with Discord."""

    challenge: CaptchaChallenge | None
    requires_captcha: bool
    requires_account: bool


def _get_providers(request: Request) -> dict[str, CaptchaProvider]:
    providers: dict[str, CaptchaProvider] = getattr(
        request.app.state, "discord_webapi_captcha_providers", {}
    )
    return providers


def _get_provider(request: Request, kind: str) -> CaptchaProvider:
    provider = _get_providers(request).get(kind)
    if provider is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No captcha provider registered for {kind!r}"
        )
    return provider


def _get_gate(request: Request, gate: CaptchaGate | None) -> CaptchaGate:
    resolved = gate or getattr(request.app.state, "discord_webapi_captcha_gate", None)
    if resolved is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No CaptchaGate configured -- pass gate=... to build_captcha_router() or "
            "set app.state.discord_webapi_captcha_gate",
        )
    return resolved


def build_captcha_router(
    *,
    gate: CaptchaGate | None = None,
    verify_rate_limiter: TokenBucketLimiter | None = None,
) -> APIRouter:
    """`gate=None` (the default) reads `app.state.discord_webapi_captcha_gate`
    at request time -- the single-gate case. Pass an explicit `gate=` to
    bind this particular router mount to one gate regardless of app
    state, so you can mount the router more than once (each under its own
    `prefix=`) for more than one gate purpose at once -- see the module
    docstring."""
    limiter = verify_rate_limiter or _DEFAULT_VERIFY_LIMITER
    router = APIRouter(prefix="/api/captcha", tags=["captcha"])

    @router.get("/challenge")
    async def create_challenge(kind: str, request: Request) -> CaptchaChallenge:
        provider = _get_provider(request, kind)
        return await provider.issue()

    @router.post("/verify")
    async def verify_challenge(body: CaptchaVerifyRequest, request: Request) -> CaptchaVerifyResult:
        # Keyed by client IP, not an authenticated user -- this endpoint is
        # meant to protect pages that don't require login (a public signup
        # form, ...), so there's no user id to key on the way the other
        # dashboard write endpoints do. Each self-hosted provider also
        # independently bounds guesses per challenge_id (see
        # `captcha._shared.verify_pending_challenge`); this is a second,
        # coarser layer against one IP hammering many different challenges.
        client_host = request.client.host if request.client else "unknown"
        limiter.check(client_host)
        provider = _get_provider(request, body.kind)
        ok = await provider.verify(body.challenge_id, body.response)
        return CaptchaVerifyResult(verified=ok)

    @router.get("/gate/{token}")
    async def get_gate_info(token: str, request: Request) -> GateInfo:
        resolved_gate = _get_gate(request, gate)
        info = await resolved_gate.get_info(token)
        if info is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "This verification link has expired or was already used"
            )
        return GateInfo(**info)

    @router.post("/gate/{token}/verify")
    async def verify_gate(
        token: str,
        body: GateVerifyRequest,
        request: Request,
        user: DiscordUser | None = Depends(get_current_user_optional),
    ) -> GateVerifyResult:
        limiter.check(token)
        resolved_gate = _get_gate(request, gate)
        result = await resolved_gate.verify(
            token,
            body.captcha_response,
            authenticated_user_id=user.id if user is not None else None,
            signals=body.signals,
            client_ip=request.client.host if request.client else None,
        )
        return GateVerifyResult(
            verified=result.verified, failed_check=result.failed_check, detail=result.detail
        )

    return router
