"""Path-trace captcha -- draw a thick line and ask the user to trace it
with a mouse or a finger. The frontend renders the line from the point
list in `params`, captures the pointer path, and posts it back; the server
checks the traced points stay within tolerance of the line and cover it
end to end.

Threat model, honestly: this is an *interaction* challenge, harder to
automate than reading a static distorted image (which modern OCR/vision
models solve trivially) because a bot has to synthesize a plausible
pointer path. It is **not** a cryptographic guarantee -- the line itself
is delivered to the client so it can be drawn, which means a determined
script can read it and submit a matching trace. Treat it as UX-level
friction and layer it with proof-of-work (cost) and account binding
(identity); don't rely on it alone. Needs no extra dependency (stdlib
`math`/`json`).
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

_WIDTH = 320
_HEIGHT = 160
_MAX_TRACE_POINTS = 5000  # reject an implausibly huge payload rather than chew on it
# A hard cap on the raw string BEFORE json.loads, so a multi-megabyte body
# can't force us to parse it just to then reject it on point count. 5000
# points of "[123.4,56.7]," is well under this.
_MAX_RESPONSE_CHARS = 200_000


def _dist_point_to_segment(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _dist_point_to_polyline(p: tuple[float, float], polyline: list[tuple[float, float]]) -> float:
    return min(
        _dist_point_to_segment(p, polyline[i], polyline[i + 1])
        for i in range(len(polyline) - 1)
    )


class PathTraceProvider:
    """`CaptchaProvider` that issues a wavy line and passes if the pointer
    trace (a) never strays further than `tolerance` from the line and (b)
    passes within `tolerance` of every vertex (so the user traced the whole
    line, not just a piece)."""

    kind = "path-trace"

    def __init__(
        self,
        store: CaptchaStore,
        *,
        tolerance: float = 24.0,
        vertices: int = 6,
        ttl: timedelta = timedelta(minutes=10),
        max_attempts: int = 5,
    ) -> None:
        self.store = store
        self.tolerance = tolerance
        self.vertices = max(3, vertices)
        self.ttl = ttl
        self.max_attempts = max_attempts

    def _make_path(self) -> list[list[float]]:
        # A smooth-ish sine curve across the width, randomized per issue so
        # the same-looking line isn't served twice.
        phase = random.uniform(0, 2 * math.pi)
        amplitude = random.uniform(30, 50)
        mid = _HEIGHT / 2
        left, right = 20.0, _WIDTH - 20.0
        path: list[list[float]] = []
        for i in range(self.vertices):
            frac = i / (self.vertices - 1)
            x = left + frac * (right - left)
            y = mid + amplitude * math.sin(phase + frac * math.pi * 1.5)
            path.append([round(x, 1), round(y, 1)])
        return path

    async def issue(self) -> CaptchaChallenge:
        path = self._make_path()
        challenge_id = secrets.token_urlsafe(16)
        now = datetime.now(UTC)
        await self.store.create(
            PendingCaptcha(
                challenge_id=challenge_id,
                kind=self.kind,
                answer=json.dumps({"path": path, "tolerance": self.tolerance}),
                created_at=now,
                expires_at=now + self.ttl,
            )
        )
        return CaptchaChallenge(
            challenge_id=challenge_id,
            kind=self.kind,
            prompt="Trace the line from start to end with your mouse or finger.",
            params={
                "path": path,
                "tolerance": self.tolerance,
                "line_width": 20,
                "width": _WIDTH,
                "height": _HEIGHT,
            },
            expires_at=now + self.ttl,
        )

    async def verify(self, challenge_id: str, response: str) -> bool:
        """`response` is a JSON array of `[x, y]` pointer samples."""

        def _verifier(pending: PendingCaptcha) -> bool:
            if len(response) > _MAX_RESPONSE_CHARS:
                return False
            try:
                trace_raw = json.loads(response)
            except (TypeError, ValueError):
                return False
            if not isinstance(trace_raw, list) or not (2 <= len(trace_raw) <= _MAX_TRACE_POINTS):
                return False
            try:
                trace = [(float(pt[0]), float(pt[1])) for pt in trace_raw]
            except (TypeError, ValueError, IndexError):
                return False

            spec = json.loads(pending.answer)
            tolerance = spec["tolerance"]
            path = [(float(x), float(y)) for x, y in spec["path"]]

            # (a) no wild excursions: every sample is near the line
            if any(_dist_point_to_polyline(pt, path) > tolerance for pt in trace):
                return False
            # (b) full coverage: every vertex has a nearby sample
            for vertex in path:
                if min(math.hypot(vertex[0] - t[0], vertex[1] - t[1]) for t in trace) > tolerance:
                    return False
            return True

        return await check_pending_challenge(
            self.store, challenge_id, max_attempts=self.max_attempts, verifier=_verifier
        )
