"""Exercises CaptchaGate end to end -- the bot-gated verification flow
the giveaway-bot scenario in captcha/gate.py's docstring describes:
create a verification link, render its challenge, solve it, and confirm
the bot side is notified over Transport the moment it's solved."""

import asyncio
from datetime import timedelta

from discord_webapi.captcha.checks import PredicateCheck, VerificationContext
from discord_webapi.captcha.events import CaptchaVerified
from discord_webapi.captcha.gate import CaptchaGate
from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
from discord_webapi.captcha.providers.math_captcha import MathCaptchaProvider
from discord_webapi.transport import InProcessTransport


def _make_gate(**kwargs: object) -> CaptchaGate:
    return CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        MathCaptchaProvider(MemoryCaptchaStore()),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_create_verification_returns_a_token_and_challenge() -> None:
    gate = _make_gate()

    request = await gate.create_verification(
        user_id=100, guild_id=999, purpose="giveaway_entry", metadata={"giveaway_id": "abc"}
    )

    assert request.token
    assert request.user_id == 100
    assert request.guild_id == 999
    assert request.purpose == "giveaway_entry"
    assert request.metadata == {"giveaway_id": "abc"}
    assert request.challenge.image_data_uri is not None
    assert request.verified is False


async def test_get_challenge_returns_the_same_challenge_the_link_was_created_with() -> None:
    gate = _make_gate()
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")

    challenge = await gate.get_challenge(request.token)

    assert challenge is not None
    assert challenge.challenge_id == request.challenge.challenge_id


async def test_get_challenge_of_unknown_token_is_none() -> None:
    gate = _make_gate()

    assert await gate.get_challenge("never-issued") is None


async def test_full_giveaway_scenario_verify_notifies_the_bot_side() -> None:
    """The exact scenario CaptchaGate was built for: a giveaway bot's
    /join creates a verification link, DMs it to the user (not modeled
    here -- that's the bot's own choice of delivery), the user solves it
    on the web, and the bot -- subscribed via on_verified() -- gets told
    "you're in!" the instant it's solved, without polling."""
    gate = _make_gate()
    notified: list[CaptchaVerified] = []

    async def on_verified(event: CaptchaVerified) -> None:
        notified.append(event)

    gate.on_verified(on_verified)

    request = await gate.create_verification(
        user_id=100, guild_id=999, purpose="giveaway_entry", metadata={"giveaway_id": "abc"}
    )
    store: MemoryCaptchaStore = gate.provider.store  # type: ignore[attr-defined]
    pending = await store.get(request.challenge.challenge_id)
    assert pending is not None

    ok = await gate.verify(request.token, pending.answer)
    await asyncio.sleep(0.05)  # let InProcessTransport's fire-and-forget dispatch run

    assert ok.verified is True
    assert ok.passed == ["captcha"]
    assert len(notified) == 1
    assert notified[0].token == request.token
    assert notified[0].user_id == 100
    assert notified[0].guild_id == 999
    assert notified[0].purpose == "giveaway_entry"
    assert notified[0].metadata == {"giveaway_id": "abc"}
    assert notified[0].checks_passed == ["captcha"]


async def test_verify_with_the_wrong_answer_does_not_notify_the_bot_side() -> None:
    gate = _make_gate()
    notified: list[CaptchaVerified] = []
    gate.on_verified(lambda event: notified.append(event))  # type: ignore[arg-type,return-value]

    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    ok = await gate.verify(request.token, "definitely-wrong")

    assert ok.verified is False
    assert ok.failed_check == "captcha"
    assert notified == []


async def test_verify_is_idempotent_once_already_solved() -> None:
    """A page refresh re-posting the same solved form must not re-check
    the provider (which could reject a second use of a one-time answer) --
    it should just confirm "yes, already verified"."""
    gate = _make_gate()
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    store: MemoryCaptchaStore = gate.provider.store  # type: ignore[attr-defined]
    pending = await store.get(request.challenge.challenge_id)
    assert pending is not None

    first = await gate.verify(request.token, pending.answer)
    second = await gate.verify(request.token, "anything-at-all")

    assert first.verified is True
    assert second.verified is True


async def test_get_challenge_after_verification_is_none() -> None:
    """A solved link has nothing left to show -- re-visiting it shouldn't
    render a stale challenge."""
    gate = _make_gate()
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    store: MemoryCaptchaStore = gate.provider.store  # type: ignore[attr-defined]
    pending = await store.get(request.challenge.challenge_id)
    assert pending is not None
    await gate.verify(request.token, pending.answer)

    assert await gate.get_challenge(request.token) is None


async def test_expired_verification_is_treated_as_gone() -> None:
    gate = _make_gate(ttl=timedelta(seconds=-1))
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")

    assert await gate.get_challenge(request.token) is None
    assert not await gate.verify(request.token, "anything")


async def test_verify_of_unknown_token_is_false() -> None:
    gate = _make_gate()

    assert not await gate.verify("never-issued", "anything")


# -- account binding: the core "which account, not just a human" trust anchor --


async def test_account_only_gate_requires_the_right_signed_in_user() -> None:
    """require_captcha=False, require_account=True -- no image, the user
    just has to be signed in as the exact Discord account the link was
    issued for. A forwarded link solved by someone else fails."""
    gate = CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        require_captcha=False,
        require_account=True,
    )
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")

    # no captcha challenge was issued for an account-only gate
    assert request.challenge is None

    # not signed in -> fails
    assert not await gate.verify(request.token)
    # signed in as the wrong account -> fails
    wrong = await gate.verify(request.token, authenticated_user_id=999)
    assert wrong.verified is False
    assert wrong.failed_check == "account"
    # signed in as the right account -> passes
    right = await gate.verify(request.token, authenticated_user_id=100)
    assert right.verified is True
    assert right.passed == ["account"]


async def test_safety_mode_requires_both_captcha_and_account() -> None:
    gate = CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        MathCaptchaProvider(MemoryCaptchaStore()),
        require_captcha=True,
        require_account=True,
    )
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    store: MemoryCaptchaStore = gate.provider.store  # type: ignore[union-attr]
    pending = await store.get(request.challenge.challenge_id)
    assert pending is not None

    # right captcha but not signed in -> account check blocks it
    only_captcha = await gate.verify(request.token, pending.answer)
    assert only_captcha.verified is False
    assert only_captcha.failed_check == "account"

    # right captcha AND right account -> both pass (account runs first, the
    # consuming captcha check last -- see CaptchaGate.__init__)
    both = await gate.verify(request.token, pending.answer, authenticated_user_id=100)
    assert both.verified is True
    assert both.passed == ["account", "captcha"]


async def test_click_only_gate_verifies_on_possession_of_the_link_alone() -> None:
    """No captcha, no account -- an empty check list. Merely POSTing to the
    valid (secret, one-time) token verifies it. The lowest-friction mode."""
    gate = CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        require_captcha=False,
        require_account=False,
    )
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")

    result = await gate.verify(request.token)

    assert result.verified is True
    assert result.passed == []


async def test_extra_checks_let_you_stack_your_own_layer() -> None:
    """The cake-layers case: our captcha layer plus the consumer's own
    check (here a trivial signal-based PredicateCheck). Both must pass."""
    seen_signals: list[dict] = []

    async def has_valid_signal(ctx: VerificationContext) -> bool:
        seen_signals.append(ctx.signals)
        return ctx.signals.get("passed_client_side_check") is True

    gate = CaptchaGate(
        InProcessTransport(),
        MemoryVerificationStore(),
        MathCaptchaProvider(MemoryCaptchaStore()),
        extra_checks=[PredicateCheck("client-signal", has_valid_signal)],
    )
    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    store: MemoryCaptchaStore = gate.provider.store  # type: ignore[union-attr]
    pending = await store.get(request.challenge.challenge_id)
    assert pending is not None

    # captcha right but the custom signal missing -> the extra check blocks it
    blocked = await gate.verify(request.token, pending.answer, signals={})
    assert blocked.verified is False
    assert blocked.failed_check == "client-signal"

    # captcha right AND the custom signal present -> both pass
    ok = await gate.verify(
        request.token, pending.answer, signals={"passed_client_side_check": True}
    )
    assert ok.verified is True
    assert ok.passed == ["client-signal", "captcha"]


def test_require_captcha_without_a_provider_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="CaptchaProvider"):
        CaptchaGate(InProcessTransport(), MemoryVerificationStore(), require_captcha=True)
