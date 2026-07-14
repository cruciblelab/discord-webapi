from pydantic import BaseModel


class DiscordUser(BaseModel):
    """The dashboard-facing view of a logged-in Discord user."""

    id: int
    username: str
    global_name: str | None = None
    avatar: str | None = None
    guild_ids: list[int] = []
