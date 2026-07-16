from pydantic import BaseModel

EVENT_TYPE_RATELIMIT_CONFIG_CHANGED = "ratelimit_config_changed"


class RateLimitConfigChanged(BaseModel):
    """Transport event payload published whenever a `RateLimitRule` changes.

    `schema_version` lets a bot process and a web process running different
    discord-webapi versions (independent deploys, see `RedisTransport`) stay
    forward/backward tolerant instead of one choking on the other's shape.
    """

    schema_version: int = 1
    guild_id: int
    key: str
