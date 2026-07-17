"""`discord_webapi.captcha` -- pluggable captcha challenges, usable two
ways:

- **Plain web usage**: mount `build_captcha_router()`, register one or
  more `CaptchaProvider`s by name, protect any point on your own site.
- **Bot-gated verification**: `CaptchaGate` ties a challenge to a
  (user_id, guild_id, purpose) and publishes a Transport event the moment
  it's solved -- see `discord_webapi.captcha.gate` for the giveaway-bot
  scenario this was built for.

Two self-hosted providers ship here (`MathCaptchaProvider`,
`TextCaptchaProvider` -- both need the `discord-webapi[captcha]` extra,
Pillow, for real distorted-image rendering), plus two third-party widget
wrappers (`ReCaptchaProvider`, `HCaptchaProvider` -- need only `httpx`,
already a core dependency). Write your own provider for anything else by
implementing `CaptchaProvider` -- no inheritance needed, same "bring your
own" pattern as every Store in this library.
"""

from typing import TYPE_CHECKING

from discord_webapi.captcha.api import build_captcha_router
from discord_webapi.captcha.base import CaptchaProvider, CaptchaStore, VerificationStore
from discord_webapi.captcha.checks import (
    AccountMatchCheck,
    CaptchaCheck,
    CheckOutcome,
    PredicateCheck,
    VerificationCheck,
    VerificationContext,
)
from discord_webapi.captcha.events import EVENT_TYPE_CAPTCHA_VERIFIED, CaptchaVerified
from discord_webapi.captcha.gate import CaptchaGate, CheckResult
from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
from discord_webapi.captcha.models import CaptchaChallenge, PendingCaptcha, VerificationRequest
from discord_webapi.captcha.providers.hcaptcha import HCaptchaProvider
from discord_webapi.captcha.providers.math_captcha import MathCaptchaProvider
from discord_webapi.captcha.providers.path_trace import PathTraceProvider
from discord_webapi.captcha.providers.proof_of_work import ProofOfWorkProvider
from discord_webapi.captcha.providers.recaptcha import ReCaptchaProvider
from discord_webapi.captcha.providers.text_captcha import TextCaptchaProvider
from discord_webapi.captcha.replay_guard import (
    MemoryTrajectoryFingerprintStore,
    RepeatedMovementCheck,
    TrajectoryFingerprintStore,
    fingerprint_trajectory,
)
from discord_webapi.captcha.scoring import (
    ScoringHeuristic,
    SignalScoreCheck,
    default_behavior_heuristics,
)
from discord_webapi.captcha.signals import (
    reject_webdriver,
    require_min_interaction_ms,
    require_signal_flag,
)

if TYPE_CHECKING:
    from discord_webapi.captcha.sql import (
        SQLCaptchaStore,
        SQLTrajectoryFingerprintStore,
        SQLVerificationStore,
    )

__all__ = [
    "EVENT_TYPE_CAPTCHA_VERIFIED",
    "AccountMatchCheck",
    "CaptchaChallenge",
    "CaptchaCheck",
    "CaptchaGate",
    "CaptchaProvider",
    "CaptchaStore",
    "CaptchaVerified",
    "CheckOutcome",
    "CheckResult",
    "HCaptchaProvider",
    "MathCaptchaProvider",
    "MemoryCaptchaStore",
    "MemoryTrajectoryFingerprintStore",
    "MemoryVerificationStore",
    "PathTraceProvider",
    "PendingCaptcha",
    "PredicateCheck",
    "ProofOfWorkProvider",
    "ReCaptchaProvider",
    "RepeatedMovementCheck",
    "SQLCaptchaStore",
    "SQLTrajectoryFingerprintStore",
    "SQLVerificationStore",
    "ScoringHeuristic",
    "SignalScoreCheck",
    "TextCaptchaProvider",
    "TrajectoryFingerprintStore",
    "VerificationCheck",
    "VerificationContext",
    "VerificationRequest",
    "VerificationStore",
    "build_captcha_router",
    "default_behavior_heuristics",
    "fingerprint_trajectory",
    "reject_webdriver",
    "require_min_interaction_ms",
    "require_signal_flag",
]


def __getattr__(name: str) -> object:
    # SQL* stores need the optional `sql` extra (`discord-webapi[sql]`) --
    # imported lazily so the base package never requires SQLAlchemy.
    if name in ("SQLCaptchaStore", "SQLVerificationStore", "SQLTrajectoryFingerprintStore"):
        from discord_webapi.captcha import sql

        return getattr(sql, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
