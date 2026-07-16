from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CaptchaChallenge(BaseModel):
    """What a `CaptchaProvider.issue()` hands back for the frontend to
    render. Self-hosted providers (Math/Text) set `image_data_uri` (a
    `data:image/png;base64,...` URI, ready for an `<img src="...">`).
    Third-party widget providers (reCAPTCHA/hCaptcha) set `site_key`
    instead -- their own JS embed does the rendering, not us.
    """

    challenge_id: str
    kind: str
    prompt: str
    image_data_uri: str | None = None
    site_key: str | None = None
    expires_at: datetime | None = None


class PendingCaptcha(BaseModel):
    """A self-hosted provider's own record of "challenge_id X's correct
    answer is Y" -- internal to `CaptchaStore`, never sent to the
    frontend. Not used by third-party providers at all (Google/hCaptcha
    hold their own challenge state, this library never sees it)."""

    challenge_id: str
    kind: str
    answer: str
    attempts: int = 0
    created_at: datetime
    expires_at: datetime


class VerificationRequest(BaseModel):
    """One bot-gated verification -- e.g. "prove you're human before
    joining this giveaway." Created by `CaptchaGate.create_verification()`,
    resolved (and `verified` flipped to `True`) when the embedded
    `challenge` is solved. `purpose`/`metadata` are entirely yours -- the
    gate never interprets them, it just carries them through to the
    `captcha_verified` Transport event so your bot-side handler knows what
    to do next (e.g. `purpose="giveaway_entry"`,
    `metadata={"giveaway_id": "..."}`).
    """

    token: str
    user_id: int
    guild_id: int | None = None
    purpose: str
    metadata: dict[str, Any] = {}
    challenge: CaptchaChallenge
    verified: bool = False
    created_at: datetime
    expires_at: datetime
