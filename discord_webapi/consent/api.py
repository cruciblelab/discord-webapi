from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.consent.models import ConsentRecord
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.dashboard_ratelimit_dependency import rate_limit_dependency
from discord_webapi.storage.base import ConsentStore

_DEFAULT_WRITE_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_consent_store(request: Request) -> ConsentStore:
    store: ConsentStore = request.app.state.discord_webapi_consent_store
    return store


class ConsentPatch(BaseModel):
    consent_version: str


def build_consent_router(*, write_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Account-level (not guild-scoped) consent-record API. Only mounted
    when `enable_cookie_consent=True` — see `DiscordWebAPI.install`. The
    notice text/UI is entirely the consumer's own -- this just persists
    "user X acknowledged notice version Y at time Z".

    `POST` is reachable with just a session cookie/bearer token, no
    permission check beyond authentication -- same threat model as
    `/auth/discord/logout`/`/sessions`, so it gets the same rate limiting
    (keyed by user id) rather than being the one write endpoint in the
    library left unthrottled.
    """
    limiter = write_rate_limiter or _DEFAULT_WRITE_LIMITER
    router = APIRouter(prefix="/api/consent", tags=["consent"])

    @router.get("")
    async def get_consent(
        request: Request, user: DiscordUser = Depends(get_current_user)
    ) -> ConsentRecord | None:
        return await _get_consent_store(request).get(user.id)

    @router.post("")
    async def give_consent(
        body: ConsentPatch,
        request: Request,
        user: DiscordUser = Depends(get_current_user),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> ConsentRecord:
        record = ConsentRecord(
            user_id=user.id, consent_version=body.consent_version, given_at=datetime.now(UTC)
        )
        await _get_consent_store(request).set(record)
        return record

    return router
