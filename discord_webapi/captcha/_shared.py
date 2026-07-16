"""Shared verify() logic for the self-hosted providers (Math/Text) --
kept out of each provider file so the expiry/attempt-limit/one-time-use
rules can't drift between them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from discord_webapi.captcha.base import CaptchaStore


async def verify_pending_challenge(
    store: CaptchaStore,
    challenge_id: str,
    response: str,
    *,
    max_attempts: int,
    normalize: Callable[[str], str] = str.strip,
) -> bool:
    """Looks up the pending challenge, enforces expiry and a bounded
    number of guesses (so a short answer can't be brute-forced by
    unlimited attempts against one `challenge_id`), compares the
    normalized response, and always deletes the pending record on either
    a correct answer or exhausted attempts -- one-time use, no replay.
    """
    pending = await store.get(challenge_id)
    if pending is None:
        return False
    if datetime.now(UTC) > pending.expires_at:
        await store.delete(challenge_id)
        return False
    if pending.attempts >= max_attempts:
        await store.delete(challenge_id)
        return False
    if normalize(response) != pending.answer:
        await store.increment_attempts(challenge_id)
        return False
    await store.delete(challenge_id)
    return True
