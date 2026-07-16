from datetime import datetime

from pydantic import BaseModel, Field


class RateLimitRule(BaseModel):
    """A per-guild rate-limit rule, keyed by an arbitrary string.

    Unlike `commands.models.CommandOverride`, `key` has no required
    relationship to a discord.py command at all -- it can identify
    anything a consumer's own code wants rate-limited (an automod check,
    a webhook handler, a piece of a hand-written command that never goes
    through `CommandRegistry`). Enforced by `GuildRateLimiter.check()`.
    """

    guild_id: int
    key: str
    max_calls: int = Field(gt=0)
    per_seconds: float = Field(gt=0)
    updated_at: datetime
    updated_by_user_id: int | None = None


class RateLimitRulePatch(BaseModel):
    """Request body for `PUT /api/guilds/{guild_id}/ratelimits/{key}`."""

    max_calls: int = Field(gt=0)
    per_seconds: float = Field(gt=0)
