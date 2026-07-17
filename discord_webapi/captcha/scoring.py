"""Behavioral risk scoring -- the "score board" for the invisible layer.

The idea you described: don't just ask a yes/no question, watch *how* the
interaction happened and build a score out of many weak signals. A human
moving a mouse toward the widget leaves a trail; a human tap never lands on
the mathematical dead-center of a button; a real browser reports a
language and a timezone. None of these alone means anything -- together
they're a soft signal.

`SignalScoreCheck` runs a set of weighted heuristics over the
client-submitted `signals` bag and passes if the weighted average clears a
threshold. It ships with a sensible default set, but every heuristic and
weight is yours to change -- add your own, drop ours, reweight (the same
"use ours, mix, bring your own" philosophy as the checks themselves).

**Read this before you rely on it.** Every input here is submitted by the
client's JavaScript, which the client controls and can forge. This is a
*transparent heuristic* score, not a bot detector and not machine
learning: a determined bot that knows these rules can send signals that
score as human. Its honest value is raising the cost of *low-effort*
automation and giving you a tunable knob -- it is meant to run *alongside*
proof-of-work (real, unspoofable cost) and account binding (real
identity), never as the only gate. Anyone selling you a server-side
"is-a-human" verdict from client-submitted signals is overselling it; this
module is deliberately honest about being a speed bump.

What the client should collect and put in `signals` (all optional -- a
missing signal just abstains or counts against, per heuristic):

- `webdriver` (bool): `navigator.webdriver`.
- `language` (str): `navigator.language`.
- `timezone` (str): `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- `pointer_type` ("mouse"|"touch"|"pen"): from the PointerEvent.
- `pointer_moves` (int): how many pointer-move samples were seen *before*
  the click/tap -- start collecting when the pointer approaches the
  widget, not when it's clicked, so a click with zero prior movement (a
  scripted synthetic click) stands out.
- `click_offset` (number): pixels between the tap/click and the exact
  center of the target -- a dead-center (offset ~0) hit is suspiciously
  precise for a human finger/mouse.
- `interaction_ms` (number): time from the widget appearing to submit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from discord_webapi.captcha.checks import CheckOutcome, VerificationContext

# A heuristic returns a human-likeness score in [0, 1] (1 = looks human,
# 0 = looks like a bot), or None to *abstain* (the signal it needs isn't
# present or doesn't apply -- e.g. mouse-movement on a touch device).
HeuristicFn = Callable[[dict[str, Any]], float | None]


@dataclass
class ScoringHeuristic:
    name: str
    weight: float
    score: HeuristicFn


def _webdriver_absent(signals: dict[str, Any]) -> float:
    return 0.0 if signals.get("webdriver") is True else 1.0


def _has_language(signals: dict[str, Any]) -> float:
    return 1.0 if isinstance(signals.get("language"), str) and signals["language"] else 0.0


def _has_timezone(signals: dict[str, Any]) -> float:
    return 1.0 if isinstance(signals.get("timezone"), str) and signals["timezone"] else 0.0


def _pointer_movement(signals: dict[str, Any]) -> float | None:
    # On touch/pen there's no "approach" movement to expect -- abstain
    # rather than punish a legitimate mobile tap.
    if signals.get("pointer_type") in ("touch", "pen"):
        return None
    moves = signals.get("pointer_moves")
    if not isinstance(moves, int | float):
        return 0.0  # a mouse interaction that reported no movement at all
    return 1.0 if moves >= 3 else 0.0


def _click_not_dead_center(signals: dict[str, Any]) -> float | None:
    offset = signals.get("click_offset")
    if not isinstance(offset, int | float):
        return None
    # A real finger/mouse never lands on the exact mathematical center; an
    # offset under ~2px is more precise than a human, i.e. bot-like.
    return 1.0 if offset >= 2 else 0.0


def _plausible_interaction_time(signals: dict[str, Any]) -> float:
    value = signals.get("interaction_ms")
    if not isinstance(value, int | float):
        return 0.0  # a submit with no reported interaction time is suspicious
    return 1.0 if value >= 400 else 0.0


def default_behavior_heuristics() -> list[ScoringHeuristic]:
    """The built-in heuristic set. Copy and edit it (drop entries,
    reweight, append your own `ScoringHeuristic`) to tune the score to your
    own tolerance -- e.g. weight `webdriver` higher, or add a heuristic
    reading your own custom signal."""
    return [
        ScoringHeuristic("webdriver-absent", 3.0, _webdriver_absent),
        ScoringHeuristic("pointer-movement", 2.0, _pointer_movement),
        ScoringHeuristic("click-not-dead-center", 2.0, _click_not_dead_center),
        ScoringHeuristic("has-language", 1.0, _has_language),
        ScoringHeuristic("has-timezone", 1.0, _has_timezone),
        ScoringHeuristic("interaction-time", 1.5, _plausible_interaction_time),
    ]


class SignalScoreCheck:
    """`VerificationCheck` that scores the client's `signals` with a set of
    weighted heuristics and passes if the weighted average is at least
    `threshold`. Heuristics that abstain (return `None`) are left out of
    the average, so a touch device isn't penalized for having no mouse
    trail. The computed score and per-heuristic breakdown go into the
    outcome's `detail` for transparency/logging."""

    name = "behavior-score"

    def __init__(
        self,
        *,
        threshold: float = 0.6,
        heuristics: list[ScoringHeuristic] | None = None,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self.threshold = threshold
        self.heuristics = heuristics if heuristics is not None else default_behavior_heuristics()

    def compute(self, signals: dict[str, Any]) -> tuple[float, dict[str, float]]:
        """Returns `(score, breakdown)` without deciding pass/fail -- handy
        for logging or tuning your threshold against real traffic. `score`
        is 1.0 (nothing to go on -> benefit of the doubt) when every
        heuristic abstains."""
        breakdown: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0
        for heuristic in self.heuristics:
            value = heuristic.score(signals)
            if value is None:
                continue
            breakdown[heuristic.name] = value
            weighted_sum += value * heuristic.weight
            total_weight += heuristic.weight
        score = 1.0 if total_weight == 0 else weighted_sum / total_weight
        return score, breakdown

    async def run(self, ctx: VerificationContext) -> CheckOutcome:
        score, breakdown = self.compute(ctx.signals)
        passed = score >= self.threshold
        parts = ", ".join(f"{name}={value:.0f}" for name, value in breakdown.items())
        detail = f"score={score:.2f} (threshold {self.threshold:.2f}) [{parts}]"
        return CheckOutcome(passed, detail)
