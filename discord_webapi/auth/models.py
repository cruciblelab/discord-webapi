from datetime import datetime

from pydantic import BaseModel


class DiscordUser(BaseModel):
    """The dashboard-facing view of a logged-in Discord user."""

    id: int
    username: str
    global_name: str | None = None
    avatar: str | None = None
    guild_ids: list[int] = []


class SessionSummary(BaseModel):
    """The dashboard-facing view of one of the user's own active sessions
    -- for a "log out everywhere" / active-sessions screen. Deliberately
    excludes the encrypted Discord token fields (`Session.encrypted_*`) --
    those never need to leave the server, even to their own owner."""

    session_id: str
    created_at: datetime
    expires_at: datetime
    is_current: bool
