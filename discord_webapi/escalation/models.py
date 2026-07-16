from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class EscalationAction(StrEnum):
    """What happens when a member's violation count reaches a rule's
    `threshold`. `NONE` still records the violation and shows up in the
    dashboard/count -- useful for a rung that's purely informational
    ("log it, don't act yet") before a later threshold actually escalates.
    """

    NONE = "none"
    TIMEOUT = "timeout"
    KICK = "kick"
    BAN = "ban"


class EscalationRule(BaseModel):
    """One rung of a per-guild, per-`key` escalation ladder: "at N
    violations, do this." A `key` can have any number of rules at
    different thresholds (e.g. 3 -> timeout, 5 -> kick, 10 -> ban) --
    there are no built-in thresholds or actions anywhere in this library;
    every rung is something a server owner explicitly configured (or your
    own code set via `EscalationEngine.set_rule()`). No rules configured
    for a `(guild_id, key)` means violations are still counted, but
    nothing is ever done about them.
    """

    guild_id: int
    key: str
    threshold: int
    action: EscalationAction
    action_minutes: int | None = None
    reason: str | None = None
    updated_at: datetime
    updated_by_user_id: int | None = None


class EscalationRulePatch(BaseModel):
    """Request body for `PUT /api/guilds/{guild_id}/escalation-rules/{key}/{threshold}`."""

    action: EscalationAction
    action_minutes: int | None = None
    reason: str | None = None


class ViolationRecord(BaseModel):
    """One recorded violation, contributing to a member's count for
    `key` in `guild_id`. `source` is a free-form label for where it came
    from (e.g. `"warn"`, `"automod.spam"`, your own command's name) --
    purely informational, not used for matching against rules (that's
    `key` alone), so you can see in the raw data what actually triggered
    each violation even if several sources feed the same `key`.
    """

    guild_id: int
    user_id: int
    key: str
    source: str | None = None
    reason: str | None = None
    created_at: datetime


class EscalationOutcome(BaseModel):
    """What `EscalationEngine.record_violation()` did, for the caller to
    report back to whoever triggered the violation (a moderator, an
    automod notice, ...)."""

    count: int
    triggered_rule: EscalationRule | None = None
