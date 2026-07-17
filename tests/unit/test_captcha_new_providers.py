"""Exercises the proof-of-work and path-trace providers against their real
verification logic -- a genuine hashcash search for PoW, real geometry for
path-trace, no mocks."""

import hashlib
import json

import pytest

from discord_webapi.captcha.memory import MemoryCaptchaStore
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


async def test_path_trace_rejects_a_straight_shortcut_across_many_issues() -> None:
    # Regression check for a real bug: with only "every sample within
    # `tolerance` of the polyline" + "every vertex has a nearby sample", a
    # dead-straight diagonal between the endpoints passes both whenever the
    # issued wave's bulge from its own chord happens to be <= tolerance --
    # which a purely random sine hit for a real fraction of issues (~4-5%
    # of them landed a bulge below the 24px default tolerance). The first
    # fix attempt added a "did the trace bulge enough" check that was dead
    # code (vertex-coverage already implies it), so it did nothing for the
    # small-bulge case; the real fix guarantees _make_path bulges >
    # tolerance. Loop many issues so a lucky flat wave can't hide the bug.
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    for _ in range(200):
        challenge = await provider.issue()
        path = challenge.params["path"]
        start, end = path[0], path[-1]
        straight_chord = json.dumps(_sample_along([start, end], per_segment=20))
        assert await provider.verify(challenge.challenge_id, straight_chord) is False


async def test_path_trace_issued_wave_always_bulges_past_tolerance() -> None:
    # The generation-side guarantee the straight-shortcut rejection relies
    # on: no matter what the random sine does, the issued wave strays from
    # its own start->end chord by more than `tolerance`.
    from discord_webapi.captcha.providers.path_trace import _chord_bulge

    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    for _ in range(200):
        challenge = await provider.issue()
        assert _chord_bulge(challenge.params["path"]) > provider.tolerance


async def test_path_trace_rejects_an_oversized_payload() -> None:
    store = MemoryCaptchaStore()
    provider = PathTraceProvider(store)
    challenge = await provider.issue()

    huge = "[" + ",".join("[0,0]" for _ in range(60_000)) + "]"  # > 200k chars
    assert await provider.verify(challenge.challenge_id, huge) is False
