"""Exercises CaptchaGate end to end -- the bot-gated verification flow
the giveaway-bot scenario in captcha/gate.py's docstring describes:
create a verification link, render its challenge, solve it, and confirm
the bot side is notified over Transport the moment it's solved."""

import asyncio
from datetime import timedelta

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

    assert ok is True
    assert len(notified) == 1
    assert notified[0].token == request.token
    assert notified[0].user_id == 100
    assert notified[0].guild_id == 999
    assert notified[0].purpose == "giveaway_entry"
    assert notified[0].metadata == {"giveaway_id": "abc"}


async def test_verify_with_the_wrong_answer_does_not_notify_the_bot_side() -> None:
    gate = _make_gate()
    notified: list[CaptchaVerified] = []
    gate.on_verified(lambda event: notified.append(event))  # type: ignore[arg-type,return-value]

    request = await gate.create_verification(user_id=100, purpose="giveaway_entry")
    ok = await gate.verify(request.token, "definitely-wrong")

    assert ok is False
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

    assert first is True
    assert second is True


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
    assert await gate.verify(request.token, "anything") is False


async def test_verify_of_unknown_token_is_false() -> None:
    gate = _make_gate()

    assert await gate.verify("never-issued", "anything") is False
