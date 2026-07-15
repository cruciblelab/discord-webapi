from pydantic import BaseModel


class ManageableGuild(BaseModel):
    """A guild from the logged-in user's own Discord guild list that this
    bot is also in, and where the user has "Manage Server" (or
    administrator) -- i.e. a candidate for a "pick a server to manage"
    screen. See `commands.bridge.list_manageable_guilds`."""

    guild_id: int
    name: str
    icon_url: str | None = None
