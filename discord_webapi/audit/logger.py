from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from discord_webapi.audit.models import AuditLogEntry

if TYPE_CHECKING:
    from discord_webapi.storage.base import AuditStore


class AuditLogger:
    """Thin wrapper around an `AuditStore`. Entirely opt-in: if the library
    consumer never turns on `enable_audit_log`, no `AuditLogger` is
    constructed and no code path here ever runs — this is not something
    every project is required to carry."""

    def __init__(self, store: AuditStore) -> None:
        self.store = store

    async def record(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        action: str,
        target: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        await self.store.record(
            AuditLogEntry(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                action=action,
                target=target,
                detail=detail or {},
                created_at=datetime.now(UTC),
            )
        )
