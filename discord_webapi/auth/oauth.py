from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.requests import HTTPConnection

from discord_webapi.auth.models import DiscordUser, SessionSummary
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.exceptions import InvalidStateError, SessionExpiredError
from discord_webapi.storage.base import Session, SessionStore
from discord_webapi.storage.memory import MemorySessionStore

_STATE_COOKIE_MAX_AGE_SECONDS = 300
_DEFAULT_SESSION_MANAGEMENT_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)
_TOKEN_REFRESH_SKEW = timedelta(seconds=60)
_MOBILE_STATE_SUFFIX = ".mobile"


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_encryption_keys(keys: bytes | list[bytes]) -> list[bytes]:
    return [keys] if isinstance(keys, bytes) else list(keys)


def _extract_bearer_token(request: HTTPConnection) -> str | None:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        return None
    return header.removeprefix("Bearer ").strip() or None


class DiscordAuth:
    """Discord OAuth2 login for dashboards, mounted as ready-made FastAPI routes.

    Session model: a single opaque `session_id` backed by a server-side
    `SessionStore` row. Discord's own access/refresh tokens are encrypted at
    rest and never sent to the client. There is no separate JWT lifecycle —
    revoking access is deleting the session row.

    The same `session_id` works two ways, so the identical auth/authz/
    commands surface is usable from a browser dashboard, a mobile app, or
    any other API client:
    - **Browser**: `/login` sets an httpOnly cookie; every route reads it
      automatically. This is the default (`?mobile=false`).
    - **Mobile / other API clients**: `/login?mobile=true` skips the cookie
      and instead redirects to `mobile_redirect_uri` with `session_id` as a
      query param on completion (the standard pattern for native apps using
      an in-app browser tab / ASWebAuthenticationSession, which intercepts
      the redirect rather than reading a response body or cookie jar). The
      client then sends that value as `Authorization: Bearer <session_id>`
      on every subsequent request — `get_current_user` accepts either the
      cookie or the header.
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
        mobile_redirect_uri: str | None = None,
        api_base_url: str = "https://discord.com/api/v10",
        http_client: httpx.AsyncClient | None = None,
        session_management_rate_limiter: TokenBucketLimiter | None = None,
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
        self.mobile_redirect_uri = mobile_redirect_uri
        self.api_base_url = api_base_url

        keys = _normalize_encryption_keys(encryption_keys)
        self._fernet = MultiFernet([Fernet(key) for key in keys])
        self._external_http_client = http_client
        self._refresh_locks: dict[str, asyncio.Lock] = {}
        # Protects /logout, /sessions, and /sessions/{id} (all reachable
        # with just a session cookie/bearer token, no permission check
        # beyond authentication) from being hammered by a compromised
        # low-trust session -- same threat model as the commands/app-roles
        # PATCH/PUT/DELETE endpoints' rate limiting.
        self._session_management_limiter = (
            session_management_rate_limiter or _DEFAULT_SESSION_MANAGEMENT_LIMITER
        )

    def install(self, app: FastAPI) -> None:
        app.state.discord_webapi_auth = self
        app.include_router(self._build_router())

    def _build_router(self) -> APIRouter:
        router = APIRouter(prefix="/auth/discord", tags=["discord-auth"])

        @router.get("/login")
        async def login(mobile: bool = False) -> RedirectResponse:
            if mobile and not self.mobile_redirect_uri:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "mobile=true requires DiscordAuth(mobile_redirect_uri=...) to be configured",
                )

            state = secrets.token_urlsafe(32) + (_MOBILE_STATE_SUFFIX if mobile else "")
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
            state_ok = bool(state and cookie_state and secrets.compare_digest(state, cookie_state))
            if not code or not state_ok:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth2 state") from None

            is_mobile = cookie_state is not None and cookie_state.endswith(_MOBILE_STATE_SUFFIX)
            session = await self._complete_login(code)

            if is_mobile:
                assert self.mobile_redirect_uri is not None  # enforced at /login time
                mobile_url = httpx.URL(
                    self.mobile_redirect_uri,
                    params={
                        "session_id": session.session_id,
                        "expires_at": session.expires_at.isoformat(),
                    },
                )
                response: Response = RedirectResponse(
                    str(mobile_url), status_code=status.HTTP_302_FOUND
                )
            else:
                response = RedirectResponse(
                    self.login_success_redirect, status_code=status.HTTP_302_FOUND
                )
                response.set_cookie(
                    self.session_cookie_name,
                    session.session_id,
                    max_age=int(self.session_ttl.total_seconds()),
                    httponly=True,
                    secure=self.cookie_secure,
                    samesite="lax",
                    domain=self.cookie_domain,
                )

            response.delete_cookie(self.state_cookie_name, domain=self.cookie_domain)
            return response

        @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
        async def logout(request: Request) -> Response:
            session_id = request.cookies.get(self.session_cookie_name) or _extract_bearer_token(
                request
            )
            if session_id:
                self._session_management_limiter.check(session_id)
                await self.session_store.delete(session_id)
            response = Response(status_code=status.HTTP_204_NO_CONTENT)
            response.delete_cookie(self.session_cookie_name, domain=self.cookie_domain)
            return response

        @router.get("/me")
        async def me(request: Request) -> DiscordUser:
            return await self.get_current_user(request)

        @router.get("/sessions")
        async def list_sessions(request: Request) -> list[SessionSummary]:
            user = await self.get_current_user(request)
            self._session_management_limiter.check(str(user.id))
            current_session_id = request.cookies.get(
                self.session_cookie_name
            ) or _extract_bearer_token(request)
            sessions = await self.session_store.list_by_user(user.id)
            return [
                SessionSummary(
                    session_id=session.session_id,
                    created_at=session.created_at,
                    expires_at=session.expires_at,
                    is_current=session.session_id == current_session_id,
                )
                for session in sessions
            ]

        @router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def revoke_session(session_id: str, request: Request) -> Response:
            user = await self.get_current_user(request)
            self._session_management_limiter.check(str(user.id))
            session = await self.session_store.get(session_id)
            if session is None or session.user_id != user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
            await self.session_store.delete(session_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

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

    async def get_current_user(self, request: HTTPConnection) -> DiscordUser:
        # HTTPConnection (not just Request) so this also works for a
        # WebSocket handshake -- both expose `.cookies`/`.headers`, and the
        # opt-in websocket relay (discord_webapi.web.websocket) needs to
        # authenticate connecting clients the same way HTTP routes do.
        session_id = request.cookies.get(self.session_cookie_name) or _extract_bearer_token(
            request
        )
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
        try:
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
        finally:
            # Evict once we're done with it -- otherwise this dict grows by
            # one entry per session that ever needed a refresh and never
            # shrinks, for the lifetime of the process. Safe to drop here:
            # any task still waiting on `lock` already holds its own
            # reference to this same Lock object (grabbed via `setdefault`
            # before we could remove it), so removing the dict entry only
            # affects the *next* session to need a lock -- it gets a fresh
            # one, and immediately re-reads current state above regardless.
            self._refresh_locks.pop(session.session_id, None)
