from pydantic import BaseModel


class AppRole(BaseModel):
    """A bot-owner-defined role, independent of Discord's own role/permission
    system. Satisfied if the checked user's id is in `user_ids`, or any of
    the checked user's Discord role ids is in `discord_role_ids` -- lets a
    dashboard admin fold several Discord roles (or specific people) into
    one named app-level permission (e.g. "moderator") without touching
    Discord's own role setup.
    """

    name: str
    guild_id: int
    discord_role_ids: list[int] = []
    user_ids: list[int] = []


class AppRolePatch(BaseModel):
    """Request body for `PUT /api/guilds/{guild_id}/app-roles/{name}`."""

    discord_role_ids: list[int] = []
    user_ids: list[int] = []
