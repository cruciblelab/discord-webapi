"""Exercises the behavioral SignalScoreCheck -- the transparent weighted
heuristic score over client-submitted signals."""

from datetime import UTC, datetime, timedelta

import pytest

from discord_webapi.captcha.checks import VerificationContext
from discord_webapi.captcha.models import VerificationRequest
from discord_webapi.captcha.scoring import ScoringHeuristic, SignalScoreCheck


def _ctx(signals: dict) -> VerificationContext:
    now = datetime.now(UTC)
    request = VerificationRequest(
        token="t1",
        user_id=100,
        purpose="test",
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    return VerificationContext(request=request, signals=signals)


_HUMAN = {
    "webdriver": False,
    "language": "tr-TR",
    "timezone": "Europe/Istanbul",
    "pointer_type": "mouse",
    "pointer_moves": 25,
    "click_offset": 7,
    "interaction_ms": 1500,
}
_BOT = {
    "webdriver": True,
    "pointer_type": "mouse",
    "pointer_moves": 0,
    "click_offset": 0,
    "interaction_ms": 2,
}


async def test_human_like_signals_pass() -> None:
    outcome = await SignalScoreCheck(threshold=0.6).run(_ctx(_HUMAN))

    assert outcome.passed is True
    assert "score=1.00" in (outcome.detail or "")


async def test_bot_like_signals_fail() -> None:
    outcome = await SignalScoreCheck(threshold=0.6).run(_ctx(_BOT))

    assert outcome.passed is False
    assert "score=0.00" in (outcome.detail or "")


async def test_mobile_touch_is_not_penalized_for_lacking_a_mouse_trail() -> None:
    """On a touch device there's no mouse-approach to expect, so the
    pointer-movement heuristic abstains instead of failing the tap."""
    mobile = {
        "webdriver": False,
        "language": "en-US",
        "timezone": "America/New_York",
        "pointer_type": "touch",
        "click_offset": 12,
        "interaction_ms": 900,
    }

    outcome = await SignalScoreCheck(threshold=0.6).run(_ctx(mobile))

    assert outcome.passed is True


async def test_dead_center_click_counts_against_the_score() -> None:
    """A click landing on the exact center (offset 0) is more precise than
    a human -- the click-not-dead-center heuristic scores it 0."""
    check = SignalScoreCheck()
    off_center = dict(_HUMAN, click_offset=9)
    dead_center = dict(_HUMAN, click_offset=0)

    off_score, _ = check.compute(off_center)
    dead_score, breakdown = check.compute(dead_center)

    assert off_score > dead_score
    assert breakdown["click-not-dead-center"] == 0.0


async def test_empty_signals_fall_below_the_threshold() -> None:
    outcome = await SignalScoreCheck(threshold=0.6).run(_ctx({}))

    assert outcome.passed is False


def test_compute_gives_benefit_of_the_doubt_when_everything_abstains() -> None:
    """With a heuristic set where every entry abstains on this input, there's
    nothing to hold against the user -> score 1.0 rather than 0."""
    only_pointer = SignalScoreCheck(
        heuristics=[
            ScoringHeuristic(
                "pointer",
                1.0,
                lambda s: None if s.get("pointer_type") == "touch" else 1.0,
            )
        ]
    )

    score, breakdown = only_pointer.compute({"pointer_type": "touch"})

    assert score == 1.0
    assert breakdown == {}


async def test_custom_heuristics_and_weights_are_honored() -> None:
    """The score board is fully tunable -- swap in your own heuristics."""
    always_bot = SignalScoreCheck(
        threshold=0.5,
        heuristics=[ScoringHeuristic("nope", 1.0, lambda s: 0.0)],
    )
    always_human = SignalScoreCheck(
        threshold=0.5,
        heuristics=[ScoringHeuristic("yep", 1.0, lambda s: 1.0)],
    )

    assert (await always_bot.run(_ctx(_HUMAN))).passed is False
    assert (await always_human.run(_ctx(_BOT))).passed is True


def test_threshold_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="threshold"):
        SignalScoreCheck(threshold=1.5)


async def test_scorer_composes_into_a_gate_as_an_extra_check() -> None:
    """The score board is just a VerificationCheck -- it drops into a
    gate's extra_checks alongside proof-of-work and account binding."""
    from discord_webapi.captcha.gate import CaptchaGate
    from discord_webapi.captcha.memory import MemoryVerificationStore
    from discord_webapi.transport import InProcessTransport

    gate = CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        require_captcha=False,
        extra_checks=[SignalScoreCheck(threshold=0.6)],
    )
    request = await gate.create_verification(user_id=100, purpose="signup")

    bot = await gate.verify(request.token, signals=_BOT)
    assert bot.verified is False
    assert bot.failed_check == "behavior-score"

    request2 = await gate.create_verification(user_id=100, purpose="signup")
    human = await gate.verify(request2.token, signals=_HUMAN)
    assert human.verified is True
