from fastapi import Request

from discord_webapi.auth.models import DiscordUser
from discord_webapi.auth.oauth import DiscordAuth


async def get_current_user(request: Request) -> DiscordUser:
    """FastAPI dependency: `Depends(get_current_user)`.

    Looks up the `DiscordAuth` instance that `DiscordAuth.install(app)`
    attached to `app.state`, so routes never need a direct reference to it.
    """
    auth: DiscordAuth = request.app.state.discord_webapi_auth
    return await auth.get_current_user(request)
