from pydantic import BaseModel

EVENT_TYPE_APP_ROLE_CHANGED = "app_role_changed"


class AppRoleChanged(BaseModel):
    """Transport event payload published whenever an `AppRole` is set or
    deleted, so every `AppRoleCache` sharing the same `Transport` -- not
    just the process that made the write -- invalidates its cached copy
    immediately instead of serving a stale role for up to `ttl_seconds`.
    Same cross-process invalidation pattern as `RateLimitConfigChanged`/
    `EscalationRulesChanged`/`member_updated`.

    `schema_version` lets a bot process and a web process running different
    discord-webapi versions (independent deploys, see `RedisTransport`) stay
    forward/backward tolerant instead of one choking on the other's shape.
    """

    schema_version: int = 1
    guild_id: int
    name: str
