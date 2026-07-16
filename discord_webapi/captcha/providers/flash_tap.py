"""Flash-tap captcha -- a dark screen with several dots; a few of them
flash (light up) one after another, and the user has to tap them in the
order they flashed. The frontend renders the dark canvas from `params`,
runs the flash sequence, captures the taps, and posts the tapped positions
in order; the server checks they match the flashed dots.

Threat model, honestly: like `PathTraceProvider`, this is *interaction*
friction, not a cryptographic guarantee. The dot layout and the flash
order are delivered to the client (the frontend needs them to render the
animation), so a determined script can read them out of the payload and
"tap" the right spots without ever watching the screen. Its value is (a)
being harder to automate than static OCR and (b) forcing a rendered,
timed interaction -- best combined with proof-of-work (cost) and account
binding (identity). Don't present it as bot-proof. Needs no extra
dependency (stdlib `random`/`json`).
"""

from __future__ import annotations

import json
import math
import random
import secrets
from datetime import UTC, datetime, timedelta

from discord_webapi.captcha._shared import check_pending_challenge
from discord_webapi.captcha.base import CaptchaStore
from discord_webapi.captcha.models import CaptchaChallenge, PendingCaptcha

_WIDTH = 300
_HEIGHT = 300


class FlashTapProvider:
    """`CaptchaProvider` that lays out `num_dots` dots, flashes `sequence_length`
    of them in a random order, and passes if the user taps those dots'
    positions in that order, each tap within `hit_radius` of the dot."""

    kind = "flash-tap"

    def __init__(
        self,
        store: CaptchaStore,
        *,
        num_dots: int = 6,
        sequence_length: int = 3,
        hit_radius: float = 32.0,
        flash_interval_ms: int = 700,
        ttl: timedelta = timedelta(minutes=10),
        max_attempts: int = 5,
    ) -> None:
        if sequence_length > num_dots:
            raise ValueError("sequence_length can't exceed num_dots")
        self.store = store
        self.num_dots = num_dots
        self.sequence_length = sequence_length
        self.hit_radius = hit_radius
        self.flash_interval_ms = flash_interval_ms
        self.ttl = ttl
        self.max_attempts = max_attempts

    def _make_dots(self) -> list[list[float]]:
        # Non-overlapping-ish dots on a jittered grid, so taps are
        # unambiguous (each tap clearly belongs to one dot).
        dots: list[list[float]] = []
        margin = 40
        attempts = 0
        while len(dots) < self.num_dots and attempts < 500:
            attempts += 1
            x = random.uniform(margin, _WIDTH - margin)
            y = random.uniform(margin, _HEIGHT - margin)
            if all(math.hypot(x - dx, y - dy) > self.hit_radius * 2.2 for dx, dy in dots):
                dots.append([round(x, 1), round(y, 1)])
        return dots

    async def issue(self) -> CaptchaChallenge:
        dots = self._make_dots()
        sequence = random.sample(range(len(dots)), min(self.sequence_length, len(dots)))
        expected = [dots[i] for i in sequence]
        challenge_id = secrets.token_urlsafe(16)
        now = datetime.now(UTC)
        await self.store.create(
            PendingCaptcha(
                challenge_id=challenge_id,
                kind=self.kind,
                answer=json.dumps({"expected": expected, "hit_radius": self.hit_radius}),
                created_at=now,
                expires_at=now + self.ttl,
            )
        )
        return CaptchaChallenge(
            challenge_id=challenge_id,
            kind=self.kind,
            prompt="Tap the dots in the order they flash.",
            params={
                "dots": dots,
                "sequence": sequence,
                "flash_interval_ms": self.flash_interval_ms,
                "dot_radius": 16,
                "hit_radius": self.hit_radius,
                "width": _WIDTH,
                "height": _HEIGHT,
            },
            expires_at=now + self.ttl,
        )

    async def verify(self, challenge_id: str, response: str) -> bool:
        """`response` is a JSON array of tapped `[x, y]` positions, in the
        order the user tapped them."""

        def _verifier(pending: PendingCaptcha) -> bool:
            try:
                taps_raw = json.loads(response)
            except (TypeError, ValueError):
                return False
            spec = json.loads(pending.answer)
            expected = spec["expected"]
            hit_radius = spec["hit_radius"]
            if not isinstance(taps_raw, list) or len(taps_raw) != len(expected):
                return False
            try:
                taps = [(float(pt[0]), float(pt[1])) for pt in taps_raw]
            except (TypeError, ValueError, IndexError):
                return False
            for tap, (ex, ey) in zip(taps, expected, strict=True):
                if math.hypot(tap[0] - ex, tap[1] - ey) > hit_radius:
                    return False
            return True

        return await check_pending_challenge(
            self.store, challenge_id, max_attempts=self.max_attempts, verifier=_verifier
        )
