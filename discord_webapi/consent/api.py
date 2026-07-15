from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.consent.models import ConsentRecord
from discord_webapi.storage.base import ConsentStore


def _get_consent_store(request: Request) -> ConsentStore:
    store: ConsentStore = request.app.state.discord_webapi_consent_store
    return store


class ConsentPatch(BaseModel):
    consent_version: str


def build_consent_router() -> APIRouter:
    """Account-level (not guild-scoped) consent-record API. Only mounted
    when `enable_cookie_consent=True` — see `DiscordWebAPI.install`. The
    notice text/UI is entirely the consumer's own -- this just persists
    "user X acknowledged notice version Y at time Z"."""
    router = APIRouter(prefix="/api/consent", tags=["consent"])

    @router.get("")
    async def get_consent(
        request: Request, user: DiscordUser = Depends(get_current_user)
    ) -> ConsentRecord | None:
        return await _get_consent_store(request).get(user.id)

    @router.post("")
    async def give_consent(
        body: ConsentPatch, request: Request, user: DiscordUser = Depends(get_current_user)
    ) -> ConsentRecord:
        record = ConsentRecord(
            user_id=user.id, consent_version=body.consent_version, given_at=datetime.now(UTC)
        )
        await _get_consent_store(request).set(record)
        return record

    return router
