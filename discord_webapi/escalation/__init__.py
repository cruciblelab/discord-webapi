from typing import TYPE_CHECKING

from discord_webapi.escalation.api import build_escalation_router
from discord_webapi.escalation.base import EscalationRuleStore, ViolationStore
from discord_webapi.escalation.engine import EscalationEngine
from discord_webapi.escalation.events import (
    EVENT_TYPE_ESCALATION_RULES_CHANGED,
    EscalationRulesChanged,
)
from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.escalation.models import (
    EscalationAction,
    EscalationOutcome,
    EscalationRule,
    EscalationRulePatch,
    ViolationRecord,
)

if TYPE_CHECKING:
    from discord_webapi.escalation.sql import SQLEscalationRuleStore, SQLViolationStore

__all__ = [
    "EVENT_TYPE_ESCALATION_RULES_CHANGED",
    "EscalationAction",
    "EscalationEngine",
    "EscalationOutcome",
    "EscalationRule",
    "EscalationRulePatch",
    "EscalationRuleStore",
    "EscalationRulesChanged",
    "MemoryEscalationRuleStore",
    "MemoryViolationStore",
    "SQLEscalationRuleStore",
    "SQLViolationStore",
    "ViolationRecord",
    "ViolationStore",
    "build_escalation_router",
]


def __getattr__(name: str) -> object:
    # SQL* stores need the optional `sql` extra (`discord-webapi[sql]`) --
    # imported lazily so the base package never requires SQLAlchemy.
    if name in ("SQLEscalationRuleStore", "SQLViolationStore"):
        from discord_webapi.escalation import sql

        return getattr(sql, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
