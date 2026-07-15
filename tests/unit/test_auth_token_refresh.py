import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import respx
from cryptography.fernet import Fernet

from discord_webapi.auth.oauth import DiscordAuth
from discord_webapi.storage.base import Session

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"


def _make_auth() -> DiscordAuth:
    return DiscordAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://testserver/auth/discord/callback",
        encryption_keys=Fernet.generate_key(),
        cookie_secure=False,
    )


def _expired_session(auth: DiscordAuth) -> Session:
    now = datetime.now(UTC)
    return Session(
        session_id="sess-1",
        user_id=1,
        username="tester",
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        encrypted_access_token=auth._encrypt("old-access"),
        encrypted_refresh_token=auth._encrypt("old-refresh"),
        discord_token_expires_at=now - timedelta(seconds=5),
    )


@respx.mock
async def test_refresh_updates_session_when_discord_token_expired() -> None:
    auth = _make_auth()
    session = _expired_session(auth)
    await auth.session_store.create(session)

    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 604800,
                "token_type": "Bearer",
            },
        )
    )

    refreshed = await auth._ensure_fresh_discord_token(session)

    assert auth._decrypt(refreshed.encrypted_access_token) == "new-access"
    stored = await auth.session_store.get(session.session_id)
    assert stored is not None
    assert auth._decrypt(stored.encrypted_access_token) == "new-access"
    # The per-session refresh lock must be evicted once done -- otherwise
    # this dict grows by one entry per session that ever refreshed and
    # never shrinks for the life of the process.
    assert session.session_id not in auth._refresh_locks


@respx.mock
async def test_concurrent_refresh_calls_only_hit_discord_once() -> None:
    auth = _make_auth()
    session = _expired_session(auth)
    await auth.session_store.create(session)

    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 604800,
                "token_type": "Bearer",
            },
        )
    )

    results = await asyncio.gather(
        auth._ensure_fresh_discord_token(session),
        auth._ensure_fresh_discord_token(session),
    )

    assert route.call_count == 1
    assert all(auth._decrypt(r.encrypted_access_token) == "new-access" for r in results)


async def test_no_refresh_when_discord_token_still_fresh() -> None:
    auth = _make_auth()
    now = datetime.now(UTC)
    session = _expired_session(auth).model_copy(
        update={"discord_token_expires_at": now + timedelta(hours=1)}
    )

    result = await auth._ensure_fresh_discord_token(session)

    assert result is session
