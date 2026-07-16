from fastapi import HTTPException, Request

from discord_webapi.auth.models import DiscordUser
from discord_webapi.auth.oauth import DiscordAuth


async def get_current_user(request: Request) -> DiscordUser:
    """FastAPI dependency: `Depends(get_current_user)`.

    Looks up the `DiscordAuth` instance that `DiscordAuth.install(app)`
    attached to `app.state`, so routes never need a direct reference to it.
    """
    auth: DiscordAuth = request.app.state.discord_webapi_auth
    return await auth.get_current_user(request)


async def get_current_user_optional(request: Request) -> DiscordUser | None:
    """Like `get_current_user`, but returns `None` instead of raising 401
    when the request isn't authenticated (or no `DiscordAuth` is installed
    at all). For endpoints where being signed in is *optional* -- e.g. a
    captcha gate whose account-check only applies in some configurations,
    so it wants the user id if there is one but must still work when there
    isn't."""
    auth: DiscordAuth | None = getattr(request.app.state, "discord_webapi_auth", None)
    if auth is None:
        return None
    try:
        return await auth.get_current_user(request)
    except HTTPException:
        return None
