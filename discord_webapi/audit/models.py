from datetime import datetime

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    """A record of one state-changing dashboard action.

    Covers writes only (command overrides, AppRole changes, ...) — never
    reads, never auth events (login/logout already have their own trail in
    `SessionStore`). Entirely opt-in: nothing writes here unless the library
    consumer turns on `enable_audit_log=True`.
    """

    guild_id: int
    actor_user_id: int
    action: str
    target: str
    detail: dict[str, object] = {}
    created_at: datetime
