"""`discord_webapi.captcha` -- a thin, backward-compatible re-export of
`webapi-captcha` (https://github.com/cruciblelab/web-api-captcha), the
standalone, Apache-2.0-licensed captcha/human-verification library this
module used to implement directly. It was split out so it can be
developed and used on its own, independently of discord-webapi.

Install it with one of:

    pip install discord-webapi[captcha]
    pip install webapi-captcha
    pip install "webapi-captcha @ git+https://github.com/cruciblelab/web-api-captcha"

`from discord_webapi.captcha import X` keeps working for every name this
module used to export directly -- new code is encouraged to `import
webapi_captcha` instead, this module exists purely for continuity.

Don't want the extra dependency? Nothing else in discord-webapi imports
this module -- write your own verification layer, or use a third-party
one; that's entirely up to you, discord-webapi doesn't care.

For the account-binding gate mode (`require_account=True`), this module
also adds two small Discord-specific conveniences that webapi_captcha
itself can't provide (it doesn't assume Discord, or any login system):
`resolve_discord_user_id` (a ready `current_user_id_resolver` wired to
this library's own OAuth session) and `build_discord_captcha_router`
(`webapi_captcha.build_captcha_router` with it pre-wired).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from discord_webapi.auth.dependencies import get_current_user_optional
from discord_webapi.auth.models import DiscordUser

try:
    from webapi_captcha import (
        DEFAULT_COOKIE_MAX_AGE,
        DEFAULT_COOKIE_NAME,
        DEFAULT_HEADLESS_UA_PATTERNS,
        DEFAULT_WIDGET_MOUNT_PATH,
        EVENT_TYPE_CAPTCHA_VERIFIED,
        AccountMatchCheck,
        AdaptiveCaptchaGate,
        AdaptiveDecision,
        AdaptiveDecisionStore,
        CaptchaChallenge,
        CaptchaCheck,
        CaptchaGate,
        CaptchaProvider,
        CaptchaStore,
        CaptchaVerified,
        CheckOutcome,
        CheckResult,
        CloudflareStyleGuard,
        FallbackCaptchaProvider,
        HCaptchaProvider,
        IPReputationChecker,
        MathCaptchaProvider,
        MemoryAdaptiveDecisionStore,
        MemoryCaptchaStore,
        MemoryTrajectoryFingerprintStore,
        MemoryTrustStore,
        MemoryVerificationStore,
        PageGuard,
        PageGuardRedirect,
        PathTraceProvider,
        PendingCaptcha,
        PredicateCheck,
        ProofOfWorkProvider,
        ReCaptchaProvider,
        RepeatedMovementCheck,
        ScoringHeuristic,
        SignalScoreCheck,
        StaticBlocklistReputationChecker,
        TextCaptchaProvider,
        TrajectoryFingerprintStore,
        TrustStore,
        TurnstileProvider,
        VerificationCheck,
        VerificationContext,
        VerificationRequest,
        VerificationStore,
        build_captcha_router,
        build_captcha_widget_router,
        build_cloudflare_style_guard,
        default_behavior_heuristics,
        fingerprint_trajectory,
        honeypot_field_empty,
        missing_accept_language,
        reject_headless_user_agent,
        reject_webdriver,
        require_min_interaction_ms,
        require_signal_flag,
        suspicious_user_agent,
    )
except ImportError as exc:
    raise ImportError(
        "discord_webapi.captcha needs the separate 'webapi-captcha' package -- "
        "captcha/human-verification was split out into its own standalone, "
        "Apache-2.0 library so it can be developed independently of "
        "discord-webapi. Install it with one of:\n"
        "\n"
        "    pip install discord-webapi[captcha]\n"
        "    pip install webapi-captcha\n"
        '    pip install "webapi-captcha @ git+https://github.com/cruciblelab/web-api-captcha"\n'
        "\n"
        "Don't want the extra dependency? You don't need it -- nothing else in "
        "discord-webapi imports discord_webapi.captcha. Write your own "
        "verification layer, or use a third-party one; that's entirely up to you."
    ) from exc

if TYPE_CHECKING:
    from fastapi import APIRouter
    from webapi_captcha.api import CurrentUserIdResolver, GateLike
    from webapi_captcha.ratelimit import TokenBucketLimiter
    from webapi_captcha.sql import (
        SQLAdaptiveDecisionStore,
        SQLCaptchaStore,
        SQLTrajectoryFingerprintStore,
        SQLTrustStore,
        SQLVerificationStore,
    )

__all__ = [
    "DEFAULT_COOKIE_MAX_AGE",
    "DEFAULT_COOKIE_NAME",
    "DEFAULT_HEADLESS_UA_PATTERNS",
    "DEFAULT_WIDGET_MOUNT_PATH",
    "EVENT_TYPE_CAPTCHA_VERIFIED",
    "AccountMatchCheck",
    "AdaptiveCaptchaGate",
    "AdaptiveDecision",
    "AdaptiveDecisionStore",
    "CaptchaChallenge",
    "CaptchaCheck",
    "CaptchaGate",
    "CaptchaProvider",
    "CaptchaStore",
    "CaptchaVerified",
    "CheckOutcome",
    "CheckResult",
    "CloudflareStyleGuard",
    "FallbackCaptchaProvider",
    "HCaptchaProvider",
    "IPReputationChecker",
    "MathCaptchaProvider",
    "MemoryAdaptiveDecisionStore",
    "MemoryCaptchaStore",
    "MemoryTrajectoryFingerprintStore",
    "MemoryTrustStore",
    "MemoryVerificationStore",
    "PageGuard",
    "PageGuardRedirect",
    "PathTraceProvider",
    "PendingCaptcha",
    "PredicateCheck",
    "ProofOfWorkProvider",
    "ReCaptchaProvider",
    "RepeatedMovementCheck",
    "SQLAdaptiveDecisionStore",
    "SQLCaptchaStore",
    "SQLTrajectoryFingerprintStore",
    "SQLTrustStore",
    "SQLVerificationStore",
    "ScoringHeuristic",
    "SignalScoreCheck",
    "StaticBlocklistReputationChecker",
    "TextCaptchaProvider",
    "TrajectoryFingerprintStore",
    "TrustStore",
    "TurnstileProvider",
    "VerificationCheck",
    "VerificationContext",
    "VerificationRequest",
    "VerificationStore",
    "build_captcha_router",
    "build_captcha_widget_router",
    "build_cloudflare_style_guard",
    "build_discord_captcha_router",
    "default_behavior_heuristics",
    "fingerprint_trajectory",
    "honeypot_field_empty",
    "missing_accept_language",
    "reject_headless_user_agent",
    "reject_webdriver",
    "require_min_interaction_ms",
    "require_signal_flag",
    "resolve_discord_user_id",
    "suspicious_user_agent",
]


async def resolve_discord_user_id(
    user: DiscordUser | None = Depends(get_current_user_optional),
) -> int | None:
    """A ready `current_user_id_resolver` for
    `build_captcha_router()`/`build_discord_captcha_router()`'s
    account-binding (`require_account=True`) gate mode -- resolves to
    the signed-in Discord user's id via this library's own OAuth
    session, or `None` if nobody's signed in."""
    return user.id if user is not None else None


def build_discord_captcha_router(
    *,
    gate: GateLike | None = None,
    current_user_id_resolver: CurrentUserIdResolver = resolve_discord_user_id,
    verify_rate_limiter: TokenBucketLimiter | None = None,
    challenge_rate_limiter: TokenBucketLimiter | None = None,
    gate_verify_ip_rate_limiter: TokenBucketLimiter | None = None,
) -> APIRouter:
    """`webapi_captcha.build_captcha_router()`, with
    `current_user_id_resolver` pre-wired to `resolve_discord_user_id`
    instead of webapi_captcha's own "nobody's ever signed in" default --
    the quick-usage path for a `require_account=True` gate checked
    against this library's own Discord login. Pass your own
    `current_user_id_resolver=` to override; everything else is
    identical to `build_captcha_router()` (see its docstring)."""
    return build_captcha_router(
        gate=gate,
        current_user_id_resolver=current_user_id_resolver,
        verify_rate_limiter=verify_rate_limiter,
        challenge_rate_limiter=challenge_rate_limiter,
        gate_verify_ip_rate_limiter=gate_verify_ip_rate_limiter,
    )


def __getattr__(name: str) -> object:
    # SQL* stores need the optional `sql` extra (`webapi-captcha[sql]`) --
    # imported lazily so the base package never requires SQLAlchemy.
    if name in (
        "SQLCaptchaStore",
        "SQLVerificationStore",
        "SQLTrajectoryFingerprintStore",
        "SQLAdaptiveDecisionStore",
        "SQLTrustStore",
    ):
        import webapi_captcha

        return getattr(webapi_captcha, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
