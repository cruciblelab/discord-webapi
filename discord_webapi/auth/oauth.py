from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from discord_webapi.auth.models import DiscordUser
from discord_webapi.exceptions import InvalidStateError, SessionExpiredError
from discord_webapi.storage.base import Session, SessionStore
from discord_webapi.storage.memory import MemorySessionStore

_STATE_COOKIE_MAX_AGE_SECONDS = 300
_TOKEN_REFRESH_SKEW = timedelta(seconds=60)


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_encryption_keys(keys: bytes | list[bytes]) -> list[bytes]:
    return [keys] if isinstance(keys, bytes) else list(keys)


class DiscordAuth:
    """Discord OAuth2 login for dashboards, mounted as ready-made FastAPI routes.

    Session model: a single opaque `session_id` cookie backed by a
    server-side `SessionStore` row. Discord's own access/refresh tokens are
    encrypted at rest and never sent to the browser. There is no separate
    JWT lifecycle — revoking access is deleting the session row.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        encryption_keys: bytes | list[bytes],
        scopes: list[str] | None = None,
        session_store: SessionStore | None = None,
        session_ttl: timedelta = timedelta(days=30),
        session_cookie_name: str = "dwa_session",
        state_cookie_name: str = "dwa_oauth_state",
        cookie_secure: bool = True,
        cookie_domain: str | None = None,
        login_success_redirect: str = "/",
        api_base_url: str = "https://discord.com/api/v10",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["identify", "guilds"]
        self.session_store = session_store or MemorySessionStore()
        self.session_ttl = session_ttl
        self.session_cookie_name = session_cookie_name
        self.state_cookie_name = state_cookie_name
        self.cookie_secure = cookie_secure
        self.cookie_domain = cookie_domain
        self.login_success_redirect = login_success_redirect
        self.api_base_url = api_base_url

        keys = _normalize_encryption_keys(encryption_keys)
        self._fernet = MultiFernet([Fernet(key) for key in keys])
        self._external_http_client = http_client
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def install(self, app: FastAPI) -> None:
        app.state.discord_webapi_auth = self
        app.include_router(self._build_router())

    def _build_router(self) -> APIRouter:
        router = APIRouter(prefix="/auth/discord", tags=["discord-auth"])

        @router.get("/login")
        async def login() -> RedirectResponse:
            state = secrets.token_urlsafe(32)
            response = RedirectResponse(
                self._authorize_url(state), status_code=status.HTTP_302_FOUND
            )
            response.set_cookie(
                self.state_cookie_name,
                state,
                max_age=_STATE_COOKIE_MAX_AGE_SECONDS,
                httponly=True,
                secure=self.cookie_secure,
                samesite="lax",
                domain=self.cookie_domain,
            )
            return response

        @router.get("/callback")
        async def callback(
            request: Request, code: str | None = None, state: str | None = None
        ) -> Response:
            cookie_state = request.cookies.get(self.state_cookie_name)
            response = RedirectResponse(
                self.login_success_redirect, status_code=status.HTTP_302_FOUND
            )
            response.delete_cookie(self.state_cookie_name, domain=self.cookie_domain)

            state_ok = bool(state and cookie_state and secrets.compare_digest(state, cookie_state))
            if not code or not state_ok:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth2 state") from None

            session = await self._complete_login(code)
            response.set_cookie(
                self.session_cookie_name,
                session.session_id,
                max_age=int(self.session_ttl.total_seconds()),
                httponly=True,
                secure=self.cookie_secure,
                samesite="lax",
                domain=self.cookie_domain,
            )
            return response

        @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
        async def logout(request: Request) -> Response:
            session_id = request.cookies.get(self.session_cookie_name)
            if session_id:
                await self.session_store.delete(session_id)
            response = Response(status_code=status.HTTP_204_NO_CONTENT)
            response.delete_cookie(self.session_cookie_name, domain=self.cookie_domain)
            return response

        @router.get("/me")
        async def me(request: Request) -> DiscordUser:
            return await self.get_current_user(request)

        return router

    def _authorize_url(self, state: str) -> str:
        params = httpx.QueryParams(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes),
                "state": state,
                "prompt": "consent",
            }
        )
        return f"https://discord.com/oauth2/authorize?{params}"

    async def _http(self) -> httpx.AsyncClient:
        if self._external_http_client is not None:
            return self._external_http_client
        return httpx.AsyncClient(base_url=self.api_base_url, timeout=10.0)

    async def _complete_login(self, code: str) -> Session:
        token_data = await self._exchange("authorization_code", code=code)
        user_payload, guild_ids = await self._fetch_user_and_guilds(token_data["access_token"])

        now = _now()
        session = Session(
            session_id=secrets.token_urlsafe(32),
            user_id=int(user_payload["id"]),
            username=user_payload["username"],
            global_name=user_payload.get("global_name"),
            avatar=user_payload.get("avatar"),
            guild_ids=guild_ids,
            created_at=now,
            expires_at=now + self.session_ttl,
            encrypted_access_token=self._encrypt(token_data["access_token"]),
            encrypted_refresh_token=self._encrypt(token_data["refresh_token"]),
            discord_token_expires_at=now + timedelta(seconds=token_data["expires_in"]),
        )
        await self.session_store.create(session)
        return session

    async def _exchange(self, grant_type: str, **fields: str) -> dict[str, Any]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": grant_type,
            **fields,
        }
        if grant_type == "authorization_code":
            data["redirect_uri"] = self.redirect_uri

        client = await self._http()
        try:
            resp = await client.post(
                "/oauth2/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return dict(resp.json())
        finally:
            if self._external_http_client is None:
                await client.aclose()

    async def _fetch_user_and_guilds(self, access_token: str) -> tuple[dict[str, Any], list[int]]:
        headers = {"Authorization": f"Bearer {access_token}"}
        client = await self._http()
        try:
            user_resp = await client.get("/users/@me", headers=headers)
            user_resp.raise_for_status()
            guilds_resp = await client.get("/users/@me/guilds", headers=headers)
            guilds_resp.raise_for_status()
            guild_ids = [int(g["id"]) for g in guilds_resp.json()]
            return user_resp.json(), guild_ids
        finally:
            if self._external_http_client is None:
                await client.aclose()

    def _encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode())

    def _decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode()
        except InvalidToken as exc:
            raise SessionExpiredError("Stored token could not be decrypted") from exc

    async def get_current_user(self, request: Request) -> DiscordUser:
        session_id = request.cookies.get(self.session_cookie_name)
        if not session_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

        session = await self.session_store.get(session_id)
        if session is None or session.expires_at < _now():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

        try:
            session = await self._ensure_fresh_discord_token(session)
        except (InvalidStateError, SessionExpiredError) as exc:
            await self.session_store.delete(session_id)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from exc

        return DiscordUser(
            id=session.user_id,
            username=session.username,
            global_name=session.global_name,
            avatar=session.avatar,
            guild_ids=session.guild_ids,
        )

    async def _ensure_fresh_discord_token(self, session: Session) -> Session:
        if session.discord_token_expires_at - _TOKEN_REFRESH_SKEW > _now():
            return session

        lock = self._refresh_locks.setdefault(session.session_id, asyncio.Lock())
        async with lock:
            # Re-read: a concurrent request may have already refreshed while we waited.
            current = await self.session_store.get(session.session_id)
            if current is None:
                raise SessionExpiredError(f"Session {session.session_id} no longer exists")
            if current.discord_token_expires_at - _TOKEN_REFRESH_SKEW > _now():
                return current

            refresh_token = self._decrypt(current.encrypted_refresh_token)
            token_data = await self._exchange("refresh_token", refresh_token=refresh_token)

            new_expiry = _now() + timedelta(seconds=token_data["expires_in"])
            updated = current.model_copy(
                update={
                    "encrypted_access_token": self._encrypt(token_data["access_token"]),
                    "encrypted_refresh_token": self._encrypt(token_data["refresh_token"]),
                    "discord_token_expires_at": new_expiry,
                }
            )
            await self.session_store.update(updated)
            return updated
