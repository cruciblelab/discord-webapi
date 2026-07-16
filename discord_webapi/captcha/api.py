"""Dashboard-facing captcha API -- two independent uses:

- **Plain web usage** (`/api/captcha/challenge`, `/api/captcha/verify`):
  protect any point on your own site (a signup form, a comment box, ...)
  with whichever registered provider you name by `kind` -- no Discord
  user/guild involved at all.
- **Bot-gated verification** (`/api/captcha/gate/{token}`): the other half
  of `discord_webapi.captcha.gate.CaptchaGate` -- renders and accepts the
  answer for a token a bot handed a specific user (see that module's
  docstring for the giveaway-bot scenario this was built for).

Neither is wired into `DiscordWebAPI.install()` automatically: unlike
audit/consent/ratelimits, there's no sensible default *provider* to fall
back to (which captcha backend, whose reCAPTCHA keys?), so mount this
yourself once you've picked and constructed one:

    app.state.discord_webapi_captcha_providers = {"math": math_provider}
    app.state.discord_webapi_captcha_gate = gate  # optional, only if you use CaptchaGate
    app.include_router(build_captcha_router())
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

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
    response: str


class CaptchaVerifyResult(BaseModel):
    verified: bool


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


def _get_gate(request: Request) -> CaptchaGate:
    gate: CaptchaGate | None = getattr(request.app.state, "discord_webapi_captcha_gate", None)
    if gate is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No CaptchaGate configured -- set app.state.discord_webapi_captcha_gate",
        )
    return gate


def build_captcha_router(*, verify_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
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
    async def get_gate_challenge(token: str, request: Request) -> CaptchaChallenge:
        gate = _get_gate(request)
        challenge = await gate.get_challenge(token)
        if challenge is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "This verification link has expired or was already used"
            )
        return challenge

    @router.post("/gate/{token}/verify")
    async def verify_gate(
        token: str, body: GateVerifyRequest, request: Request
    ) -> CaptchaVerifyResult:
        limiter.check(token)
        gate = _get_gate(request)
        ok = await gate.verify(token, body.response)
        return CaptchaVerifyResult(verified=ok)

    return router
