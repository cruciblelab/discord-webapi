"""Shared verify() lifecycle for the self-hosted providers -- kept out of
each provider file so the expiry / attempt-limit / one-time-use rules
can't drift between them.

`check_pending_challenge` owns the lifecycle (look up, expire, bound the
guesses, delete on success-or-exhaustion) and takes a `verifier` callable
for the provider-specific "is this answer correct" comparison -- string
equality for Math/Text, a hash check for proof-of-work, geometric
tolerance for the interactive ones. `verify_pending_challenge` is the
thin string-equality wrapper the simple image providers use.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from discord_webapi.captcha.base import CaptchaStore
from discord_webapi.captcha.models import PendingCaptcha


async def check_pending_challenge(
    store: CaptchaStore,
    challenge_id: str,
    *,
    max_attempts: int,
    verifier: Callable[[PendingCaptcha], bool],
) -> bool:
    """Looks up the pending challenge, enforces expiry and a bounded number
    of guesses (so a short answer can't be brute-forced by unlimited
    attempts against one `challenge_id`), runs the provider's own
    `verifier`, and always deletes the pending record on either a correct
    answer or exhausted attempts -- one-time use, no replay."""
    pending = await store.get(challenge_id)
    if pending is None:
        return False
    if datetime.now(UTC) > pending.expires_at:
        await store.delete(challenge_id)
        return False
    if pending.attempts >= max_attempts:
        await store.delete(challenge_id)
        return False
    if not verifier(pending):
        await store.increment_attempts(challenge_id)
        return False
    await store.delete(challenge_id)
    return True


async def verify_pending_challenge(
    store: CaptchaStore,
    challenge_id: str,
    response: str,
    *,
    max_attempts: int,
    normalize: Callable[[str], str] = str.strip,
) -> bool:
    """String-equality convenience over `check_pending_challenge`, used by
    the plain image providers (Math/Text) whose answer is just text."""
    return await check_pending_challenge(
        store,
        challenge_id,
        max_attempts=max_attempts,
        verifier=lambda pending: normalize(response) == pending.answer,
    )
