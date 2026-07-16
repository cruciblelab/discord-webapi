"""Exercises the proof-of-work, path-trace, and flash-tap providers
against their real verification logic -- a genuine hashcash search for
PoW, real geometry for the interactive ones, no mocks."""

import hashlib
import json

import pytest

from discord_webapi.captcha.memory import MemoryCaptchaStore
from discord_webapi.captcha.providers.flash_tap import FlashTapProvider
from discord_webapi.captcha.providers.path_trace import PathTraceProvider
from discord_webapi.captcha.providers.proof_of_work import ProofOfWorkProvider, _leading_zero_bits

# -- proof of work --


def test_leading_zero_bits_counts_correctly() -> None:
    assert _leading_zero_bits(bytes([0x00, 0xFF])) == 8
    assert _leading_zero_bits(bytes([0x0F])) == 4
    assert _leading_zero_bits(bytes([0x00, 0x00, 0x80])) == 16
    assert _leading_zero_bits(bytes([0xFF])) == 0


def _solve_pow(prefix: str, difficulty: int) -> str:
    nonce = 0
    while True:
        digest = hashlib.sha256(f"{prefix}{nonce}".encode()).digest()
        if _leading_zero_bits(digest) >= difficulty:
            return str(nonce)
        nonce += 1


async def test_pow_accepts_a_real_solution() -> None:
    store = MemoryCaptchaStore()
    provider = ProofOfWorkProvider(store, difficulty=8)
    challenge = await provider.issue()

    assert challenge.kind == "pow"
    assert challenge.image_data_uri is None
    assert challenge.params["algorithm"] == "sha256-leading-zero-bits"

    nonce = _solve_pow(challenge.params["prefix"], challenge.params["difficulty"])
    assert await provider.verify(challenge.challenge_id, nonce) is True


async def test_pow_rejects_a_nonce_that_does_not_clear_the_difficulty() -> None:
    store = MemoryCaptchaStore()
    provider = ProofOfWorkProvider(store, difficulty=20)  # a random nonce won't clear this
    challenge = await provider.issue()

    assert await provider.verify(challenge.challenge_id, "0") is False


async def test_pow_solution_is_one_time_use() -> None:
    store = MemoryCaptchaStore()
    provider = ProofOfWorkProvider(store, difficulty=8)
    challenge = await provider.issue()
    nonce = _solve_pow(challenge.params["prefix"], challenge.params["difficulty"])

    assert await provider.verify(challenge.challenge_id, nonce) is True
    assert await provider.verify(challenge.challenge_id, nonce) is False  # replay


def test_pow_rejects_a_zero_difficulty() -> None:
    with pytest.raises(ValueError, match="difficulty"):
        ProofOfWorkProvider(MemoryCaptchaStore(), difficulty=0)


# -- path trace --


def _sample_along(path: list[list[float]], per_segment: int = 6) -> list[list[float]]:
    points: list[list[float]] = []
    for i in range(len(path) - 1):
        ax, ay = path[i]
        bx, by = path[i + 1]
        for k in range(per_segment + 1):
            t = k / per_segment
            points.append([ax + (bx - ax) * t, ay + (by - ay) * t])
    return points


async def test_path_trace_accepts_a_faithful_trace() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()

    assert challenge.kind == "path-trace"
    trace = json.dumps(_sample_along(challenge.params["path"]))
    assert await provider.verify(challenge.challenge_id, trace) is True


async def test_path_trace_rejects_a_line_far_from_the_path() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()

    straight = json.dumps([[20, 5], [300, 5]])  # nowhere near the wavy line
    assert await provider.verify(challenge.challenge_id, straight) is False


async def test_path_trace_rejects_tracing_only_part_of_the_line() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()
    path = challenge.params["path"]

    half = json.dumps(_sample_along(path[: len(path) // 2]))
    assert await provider.verify(challenge.challenge_id, half) is False


async def test_path_trace_handles_malformed_input_without_crashing() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()

    assert await provider.verify(challenge.challenge_id, "not json") is False


async def test_path_trace_is_one_time_use() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()
    trace = json.dumps(_sample_along(challenge.params["path"]))

    assert await provider.verify(challenge.challenge_id, trace) is True
    assert await provider.verify(challenge.challenge_id, trace) is False


# -- flash tap --


async def test_flash_tap_accepts_the_flashed_dots_in_order() -> None:
    store = MemoryCaptchaStore()
    provider = FlashTapProvider(store, num_dots=6, sequence_length=3)
    challenge = await provider.issue()

    assert challenge.kind == "flash-tap"
    dots = challenge.params["dots"]
    sequence = challenge.params["sequence"]
    taps = json.dumps([dots[i] for i in sequence])
    assert await provider.verify(challenge.challenge_id, taps) is True


async def test_flash_tap_accepts_taps_within_the_hit_radius() -> None:
    store = MemoryCaptchaStore()
    provider = FlashTapProvider(store, num_dots=6, sequence_length=3, hit_radius=32.0)
    challenge = await provider.issue()
    dots = challenge.params["dots"]
    sequence = challenge.params["sequence"]

    jittered = json.dumps([[dots[i][0] + 10, dots[i][1] - 10] for i in sequence])  # within 32px
    assert await provider.verify(challenge.challenge_id, jittered) is True


async def test_flash_tap_rejects_far_off_taps() -> None:
    store = MemoryCaptchaStore()
    provider = FlashTapProvider(store, num_dots=6, sequence_length=3, hit_radius=32.0)
    challenge = await provider.issue()
    dots = challenge.params["dots"]
    sequence = challenge.params["sequence"]

    far = json.dumps([[dots[i][0] + 100, dots[i][1]] for i in sequence])
    assert await provider.verify(challenge.challenge_id, far) is False


async def test_flash_tap_rejects_the_wrong_number_of_taps() -> None:
    store = MemoryCaptchaStore()
    provider = FlashTapProvider(store, num_dots=6, sequence_length=3)
    challenge = await provider.issue()
    dots = challenge.params["dots"]
    sequence = challenge.params["sequence"]

    too_few = json.dumps([dots[sequence[0]]])
    assert await provider.verify(challenge.challenge_id, too_few) is False


async def test_flash_tap_is_one_time_use() -> None:
    store = MemoryCaptchaStore()
    provider = FlashTapProvider(store, num_dots=6, sequence_length=3)
    challenge = await provider.issue()
    dots = challenge.params["dots"]
    sequence = challenge.params["sequence"]
    taps = json.dumps([dots[i] for i in sequence])

    assert await provider.verify(challenge.challenge_id, taps) is True
    assert await provider.verify(challenge.challenge_id, taps) is False


def test_flash_tap_rejects_a_sequence_longer_than_the_dots() -> None:
    with pytest.raises(ValueError, match="sequence_length"):
        FlashTapProvider(MemoryCaptchaStore(), num_dots=3, sequence_length=5)
