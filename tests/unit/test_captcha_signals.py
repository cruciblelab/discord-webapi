"""Exercises the instrumentation-signal PredicateCheck helpers -- the
transparent, honest heuristics for the invisible layer."""

from datetime import UTC, datetime, timedelta

from discord_webapi.captcha.checks import VerificationContext
from discord_webapi.captcha.models import VerificationRequest
from discord_webapi.captcha.signals import (
    reject_webdriver,
    require_min_interaction_ms,
    require_signal_flag,
)


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


async def test_reject_webdriver_blocks_a_reported_webdriver() -> None:
    outcome = await reject_webdriver().run(_ctx({"webdriver": True}))

    assert outcome.passed is False
    assert "webdriver" in (outcome.detail or "")


async def test_reject_webdriver_passes_when_absent_or_false() -> None:
    assert (await reject_webdriver().run(_ctx({}))).passed is True
    assert (await reject_webdriver().run(_ctx({"webdriver": False}))).passed is True


async def test_require_signal_flag() -> None:
    check = require_signal_flag("passed_js_attestation")

    assert (await check.run(_ctx({"passed_js_attestation": True}))).passed is True
    assert (await check.run(_ctx({}))).passed is False
    assert (await check.run(_ctx({"passed_js_attestation": False}))).passed is False


async def test_require_min_interaction_ms() -> None:
    check = require_min_interaction_ms(400)

    assert (await check.run(_ctx({"interaction_ms": 900}))).passed is True
    assert (await check.run(_ctx({"interaction_ms": 3}))).passed is False
    # not reported at all -> treated as failing (a silent submit is suspicious)
    assert (await check.run(_ctx({}))).passed is False
