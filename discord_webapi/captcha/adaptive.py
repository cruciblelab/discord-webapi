"""`AdaptiveCaptchaGate` -- the Cloudflare-"Under Attack Mode" pattern:
check IP reputation first, only escalate to a visible captcha if that
connection looks suspicious; if it doesn't, ask nothing more than the
invisible layer already asks. Once someone clears it, remember that for
a while so a page refresh doesn't ask again -- captcha fatigue is a real
UX cost, not a free safety margin.

This is a distinct class from `CaptchaGate`, not a mode flag on it,
because the decision here is made *dynamically*, the first time a
verification link is actually opened (when the connecting IP is known),
rather than fixed once at construction time -- `CaptchaGate`'s
`require_captcha` is deliberately static, and retrofitting a dynamic
decision into it would have meant either breaking that simplicity for
everyone or growing a pile of conditional branches into an already-
covered, already-tested class. Composing a new small piece next to it
matches every other decision in this module: build another piece rather
than make one piece do everything.

Same "use it or don't" rule as the rest of this package: this is not
wired into anything automatically, it needs no default IP-reputation
source (see `discord_webapi.captcha.reputation` -- bring your own), and
nothing stops you from using Cloudflare Turnstile, your own adaptive
logic, or nothing at all instead.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel

from discord_webapi.captcha.base import CaptchaProvider, VerificationStore
from discord_webapi.captcha.checks import (
    AccountMatchCheck,
    CaptchaCheck,
    VerificationCheck,
    VerificationContext,
)
from discord_webapi.captcha.events import EVENT_TYPE_CAPTCHA_VERIFIED, CaptchaVerified
from discord_webapi.captcha.gate import CheckResult
from discord_webapi.captcha.models import CaptchaChallenge, VerificationRequest
from discord_webapi.captcha.reputation import IPReputationChecker
from discord_webapi.transport.base import Event, Transport


class AdaptiveDecision(BaseModel):
    """The one-time-made, then-persisted answer to "does this
    verification link need a visible captcha" -- kept separate from
    `VerificationRequest` itself (a dedicated store, not a mutation of
    the shared one) so this feature needs no changes to
    `VerificationStore`/`CaptchaGate` at all."""

    requires_captcha: bool
    challenge: CaptchaChallenge | None = None


class AdaptiveDecisionStore(Protocol):
    """Where an `AdaptiveCaptchaGate` remembers the escalation decision
    it made the first time a token's link was opened, so reloading the
    page doesn't re-roll the dice (and doesn't re-charge an IP-reputation
    lookup that might cost money) on every request."""

    async def get(self, token: str) -> AdaptiveDecision | None: ...

    async def set(self, token: str, decision: AdaptiveDecision) -> None: ...

    async def delete(self, token: str) -> None: ...


class MemoryAdaptiveDecisionStore:
    """Dict-backed `AdaptiveDecisionStore`. Zero infrastructure -- the
    default."""

    def __init__(self) -> None:
        self._decisions: dict[str, AdaptiveDecision] = {}

    async def get(self, token: str) -> AdaptiveDecision | None:
        return self._decisions.get(token)

    async def set(self, token: str, decision: AdaptiveDecision) -> None:
        self._decisions[token] = decision

    async def delete(self, token: str) -> None:
        self._decisions.pop(token, None)


class TrustStore(Protocol):
    """"Don't ask again for a while" -- once a `user_id` clears an
    `AdaptiveCaptchaGate` verification, it's marked trusted until `ttl`
    passes, so a repeat visit within that window skips both the
    IP-reputation lookup and any visible captcha entirely. Keyed by the
    Discord `user_id` (real, OAuth-backed identity, not a client-
    submitted device signal) -- deliberately the same trust anchor
    `AccountMatchCheck` uses elsewhere in this package, not a fingerprint
    that could be spoofed the way `captcha.scoring`'s heuristics can be.
    """

    async def is_trusted(self, user_id: int) -> bool: ...

    async def trust(self, user_id: int, *, ttl: timedelta) -> None: ...


class MemoryTrustStore:
    """Dict-backed `TrustStore`. Zero infrastructure -- the default."""

    def __init__(self) -> None:
        self._trusted_until: dict[int, datetime] = {}

    async def is_trusted(self, user_id: int) -> bool:
        expires_at = self._trusted_until.get(user_id)
        if expires_at is None:
            return False
        if datetime.now(UTC) > expires_at:
            del self._trusted_until[user_id]
            return False
        return True

    async def trust(self, user_id: int, *, ttl: timedelta) -> None:
        self._trusted_until[user_id] = datetime.now(UTC) + ttl


class AdaptiveCaptchaGate:
    """A `CaptchaGate`-shaped verification gate whose captcha requirement
    is decided dynamically, per verification link, the first time it's
    opened -- based on the connecting IP's reputation, not fixed up
    front. High-level flow, same idea as Cloudflare's "Under Attack
    Mode":

    1. `create_verification()` mints a token with no challenge yet --
       nothing is decided until someone actually opens the link.
    2. The first `get_info()`/`verify()` call for that token checks
       `trust_store` (skip everything if this account was recently
       cleared) and, failing that, asks `reputation.is_suspicious(ip)`.
       Suspicious -> a real captcha challenge is issued from
       `escalation_provider` and required. Not suspicious -> no visible
       captcha at all, only `require_account`/`extra_checks` (typically
       the invisible layer -- PoW + behavior score) apply.
    3. The decision is persisted in `decision_store` so a page reload
       doesn't re-roll it or re-charge a paid reputation lookup.
    4. On success, if `trust_store` is set, the user is marked trusted
       for `trust_ttl` -- their next verification (even a *different*
       token/purpose using the *same* trust_store) skips reputation
       entirely.

    Talks to the exact same bundled widget
    (`discord_webapi.captcha.widget`) and `build_captcha_router()` as
    `CaptchaGate` -- the widget already renders "no captcha" or "here's
    the challenge" based on whatever `get_info()` returns, so nothing
    about the frontend needs to know this gate is adaptive.
    """

    def __init__(
        self,
        transport: Transport,
        store: VerificationStore,
        reputation: IPReputationChecker,
        escalation_provider: CaptchaProvider,
        decision_store: AdaptiveDecisionStore,
        *,
        require_account: bool = False,
        extra_checks: Sequence[VerificationCheck] | None = None,
        trust_store: TrustStore | None = None,
        trust_ttl: timedelta = timedelta(hours=24),
        ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.transport = transport
        self.store = store
        self.reputation = reputation
        self.escalation_provider = escalation_provider
        self.decision_store = decision_store
        self.require_account = require_account
        self.extra_checks: list[VerificationCheck] = list(extra_checks or [])
        self.trust_store = trust_store
        self.trust_ttl = trust_ttl
        self.ttl = ttl

    async def create_verification(
        self,
        *,
        user_id: int,
        guild_id: int | None = None,
        purpose: str,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequest:
        """Mints a token with no challenge attached yet -- whether one is
        ever needed is decided later, the first time the link is
        actually opened (see `get_info`/`verify`)."""
        now = datetime.now(UTC)
        request = VerificationRequest(
            token=secrets.token_urlsafe(24),
            user_id=user_id,
            guild_id=guild_id,
            purpose=purpose,
            metadata=metadata or {},
            challenge=None,
            created_at=now,
            expires_at=now + self.ttl,
        )
        await self.store.create(request)
        return request

    async def get_info(self, token: str, *, client_ip: str | None = None) -> dict[str, Any] | None:
        """Same shape as `CaptchaGate.get_info()` -- what the frontend
        needs to render the right thing. Making/persisting the
        escalation decision (if not already made) happens here, since
        this is the first point at which the connecting IP is known."""
        request = await self._get_live(token)
        if request is None or request.verified:
            return None
        decision = await self._resolve_decision(token, request, client_ip)
        return {
            "challenge": decision.challenge,
            "requires_captcha": decision.requires_captcha,
            "requires_account": self.require_account,
        }

    async def verify(
        self,
        token: str,
        response: str | None = None,
        *,
        authenticated_user_id: int | None = None,
        signals: dict[str, Any] | None = None,
        client_ip: str | None = None,
    ) -> CheckResult:
        """Same contract as `CaptchaGate.verify()`. Reuses whatever
        escalation decision `get_info()` already made for this token
        (or makes one now, if the widget's info call was somehow
        skipped) -- the decision, once made, never changes for a given
        token."""
        request = await self._get_live(token)
        if request is None:
            return CheckResult(verified=False, failed_check=None, detail="link expired or unknown")
        if request.verified:
            return CheckResult(verified=True, passed=[])

        decision = await self._resolve_decision(token, request, client_ip)
        # The check that reads ctx.request.challenge (CaptchaCheck) needs
        # it there -- AdaptiveDecision is kept in its own store rather
        # than mutated onto the shared VerificationRequest, so it's
        # attached to this in-memory copy just for this call.
        request.challenge = decision.challenge

        checks: list[VerificationCheck] = []
        if self.require_account:
            checks.append(AccountMatchCheck())
        checks.extend(self.extra_checks)
        if decision.requires_captcha:
            checks.append(CaptchaCheck(self.escalation_provider))

        ctx = VerificationContext(
            request=request,
            authenticated_user_id=authenticated_user_id,
            captcha_response=response,
            signals=signals or {},
            client_ip=client_ip,
        )
        passed: list[str] = []
        for check in checks:
            outcome = await check.run(ctx)
            if not outcome.passed:
                return CheckResult(verified=False, failed_check=check.name, detail=outcome.detail)
            passed.append(check.name)

        await self.store.mark_verified(token)
        await self.decision_store.delete(token)
        if self.trust_store is not None:
            await self.trust_store.trust(request.user_id, ttl=self.trust_ttl)
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_CAPTCHA_VERIFIED,
                payload=CaptchaVerified(
                    token=token,
                    user_id=request.user_id,
                    guild_id=request.guild_id,
                    purpose=request.purpose,
                    metadata=request.metadata,
                    checks_passed=passed,
                ).model_dump(),
            )
        )
        return CheckResult(verified=True, passed=passed)

    def on_verified(
        self,
        handler: Callable[[CaptchaVerified], Awaitable[None]],
        *,
        purpose: str | None = None,
    ) -> None:
        """Identical to `CaptchaGate.on_verified` -- including the same
        `purpose=` filter, for the same reason: `captcha_verified` is one
        event type shared by every gate on a `Transport`, adaptive or
        not."""

        async def _wrapped(event: Event) -> None:
            payload = CaptchaVerified.model_validate(event.payload)
            if purpose is not None and payload.purpose != purpose:
                return
            await handler(payload)

        self.transport.subscribe(EVENT_TYPE_CAPTCHA_VERIFIED, _wrapped)

    async def _resolve_decision(
        self, token: str, request: VerificationRequest, client_ip: str | None
    ) -> AdaptiveDecision:
        existing = await self.decision_store.get(token)
        if existing is not None:
            return existing

        trusted = False
        if self.trust_store is not None:
            trusted = await self.trust_store.is_trusted(request.user_id)

        requires_captcha = False
        challenge = None
        if not trusted and client_ip is not None:
            requires_captcha = await self.reputation.is_suspicious(client_ip)
            if requires_captcha:
                challenge = await self.escalation_provider.issue()

        decision = AdaptiveDecision(requires_captcha=requires_captcha, challenge=challenge)
        await self.decision_store.set(token, decision)
        return decision

    async def _get_live(self, token: str) -> VerificationRequest | None:
        request = await self.store.get(token)
        if request is None:
            return None
        if datetime.now(UTC) > request.expires_at:
            await self.store.delete(token)
            await self.decision_store.delete(token)
            return None
        return request
