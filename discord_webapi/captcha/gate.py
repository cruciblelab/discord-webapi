"""`CaptchaGate` -- ties a `CaptchaProvider` challenge to a specific
Discord user/guild/purpose so a bot command can gate on "prove you're
human first," with the actual solving happening on the web.

Concrete scenario this was built for: a giveaway bot's `/join` command
calls `create_verification()`, sends the user the resulting link however
the bot developer chooses (a DM, an ephemeral reply -- this class doesn't
care), and replies "click the link to confirm you're human." The web side
serves that link (`discord_webapi.captcha.api.build_captcha_router()`'s
`/api/captcha/gate/{token}` endpoints render the challenge and accept the
answer). The moment it's solved, `verify()` publishes `captcha_verified`
over `Transport` -- the bot subscribes via `on_verified()` and DMs the
user "you're in!" right then, no polling needed, and it works the same
way whether the bot and the web dashboard are the same process or two
separate ones (`for_bot_process`/`for_web_process`).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from discord_webapi.captcha.base import CaptchaProvider, VerificationStore
from discord_webapi.captcha.events import EVENT_TYPE_CAPTCHA_VERIFIED, CaptchaVerified
from discord_webapi.captcha.models import CaptchaChallenge, VerificationRequest
from discord_webapi.transport.base import Event, Transport


class CaptchaGate:
    def __init__(
        self,
        transport: Transport,
        store: VerificationStore,
        provider: CaptchaProvider,
        *,
        ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.transport = transport
        self.store = store
        self.provider = provider
        self.ttl = ttl

    async def create_verification(
        self,
        *,
        user_id: int,
        guild_id: int | None = None,
        purpose: str,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequest:
        """Issues a fresh challenge from `self.provider` and wraps it in a
        one-time verification token. Hand the token (or a URL built from
        it, e.g. `f"https://yoursite.com/verify/{request.token}"`) to the
        user however you like -- DM, ephemeral interaction reply, a
        button, whatever fits your bot.
        """
        challenge = await self.provider.issue()
        now = datetime.now(UTC)
        request = VerificationRequest(
            token=secrets.token_urlsafe(24),
            user_id=user_id,
            guild_id=guild_id,
            purpose=purpose,
            metadata=metadata or {},
            challenge=challenge,
            created_at=now,
            expires_at=now + self.ttl,
        )
        await self.store.create(request)
        return request

    async def get_challenge(self, token: str) -> CaptchaChallenge | None:
        """For the web side to render: `None` if the token doesn't exist,
        already expired, or was already verified (a solved/expired link
        has nothing left to show)."""
        request = await self._get_live(token)
        if request is None or request.verified:
            return None
        return request.challenge

    async def verify(self, token: str, response: str) -> bool:
        """Checks `response` against the token's embedded challenge via
        `self.provider.verify()`. On success, marks the token verified
        (idempotent -- calling this again, e.g. a page refresh re-posting
        the same form, just confirms "yes, already verified" without
        re-checking the provider) and publishes `captcha_verified`.
        """
        request = await self._get_live(token)
        if request is None:
            return False
        if request.verified:
            return True
        ok = await self.provider.verify(request.challenge.challenge_id, response)
        if not ok:
            return False
        await self.store.mark_verified(token)
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_CAPTCHA_VERIFIED,
                payload=CaptchaVerified(
                    token=token,
                    user_id=request.user_id,
                    guild_id=request.guild_id,
                    purpose=request.purpose,
                    metadata=request.metadata,
                ).model_dump(),
            )
        )
        return True

    def on_verified(self, handler: Callable[[CaptchaVerified], Awaitable[None]]) -> None:
        """Convenience wrapper around `transport.subscribe` so bot-side
        code doesn't need to know the event type string or unwrap the
        payload itself -- `handler` receives an already-parsed
        `CaptchaVerified`."""

        async def _wrapped(event: Event) -> None:
            await handler(CaptchaVerified.model_validate(event.payload))

        self.transport.subscribe(EVENT_TYPE_CAPTCHA_VERIFIED, _wrapped)

    async def _get_live(self, token: str) -> VerificationRequest | None:
        request = await self.store.get(token)
        if request is None:
            return None
        if datetime.now(UTC) > request.expires_at:
            await self.store.delete(token)
            return None
        return request
