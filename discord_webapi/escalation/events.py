from pydantic import BaseModel

EVENT_TYPE_ESCALATION_RULES_CHANGED = "escalation_rules_changed"


class EscalationRulesChanged(BaseModel):
    """Transport event payload published whenever a guild's escalation
    ladder for `key` changes (a rule set or deleted).

    `schema_version` lets a bot process and a web process running different
    discord-webapi versions (independent deploys, see `RedisTransport`) stay
    forward/backward tolerant instead of one choking on the other's shape.
    """

    schema_version: int = 1
    guild_id: int
    key: str
