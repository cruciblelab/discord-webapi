"""The stable surface a third-party extension builds against.

Import everything you need to write a `discord-webapi`-compatible extension
from this one module::

    from discord_webapi.extensions.sdk import (
        Extension, ExtensionManifest,        # to declare yourself
        GuildRateLimiter, EscalationEngine,  # infrastructure the host hands you
        rate_limited,                        # the skeleton decorator
        check_role_hierarchy, notify_member_best_effort,  # shared helpers
    )

Everything re-exported here is part of the public, stability-promised API:
these names, and the behavior behind them, are what extensions are allowed
to depend on. Anything *not* re-exported here (a module's private
internals, `discord_webapi._something`, an undocumented attribute) is fair
game to change between versions and must not be relied on by an extension.

This is the whole reason no "plugin runtime" is needed: our own
`discord_webapi.extras` are written against exactly this surface and
nothing more, so a third-party extension using the same surface is
indistinguishable from a first-party one -- same capabilities, same
limits, no privileged hooks into core.

Note on *instances* vs *types*: an extension that rate-limits or escalates
doesn't construct its own `GuildRateLimiter`/`EscalationEngine` -- the host
application already has them (`DiscordWebAPI.rate_limiter` /
`.escalation_engine`) and passes them into your `setup(bot, *,
rate_limiter=..., escalation_engine=...)`. The types are re-exported here
for type annotations and for the rare extension that genuinely wants its
own instance; the *convention* is that the host injects its own.
"""

from __future__ import annotations

# --- declaring your extension ---
from discord_webapi.escalation import (
    EscalationAction,
    EscalationEngine,
    EscalationOutcome,
    EscalationRule,
    EscalationRuleStore,
    ViolationRecord,
    ViolationStore,
)
from discord_webapi.extensions.base import Extension
from discord_webapi.extensions.manifest import ExtensionManifest

# --- shared moderation helpers (reuse instead of re-implementing) ---
from discord_webapi.extras._shared import (
    check_role_assignable,
    check_role_hierarchy,
    notify_member_best_effort,
)

# --- the skeleton decorator (rebar for your own commands) ---
from discord_webapi.extras.skeletons import rate_limited

# --- rate limiting ---
from discord_webapi.ratelimits import GuildRateLimiter, RateLimitRule

# --- storage protocols (author your own persistent state the same way) ---
from discord_webapi.storage.base import (
    AuditStore,
    RateLimitStore,
)

# --- transport (publish/subscribe your own live-config events) ---
from discord_webapi.transport.base import Event, Transport

__all__ = [
    "AuditStore",
    "EscalationAction",
    "EscalationEngine",
    "EscalationOutcome",
    "EscalationRule",
    "EscalationRuleStore",
    "Event",
    "Extension",
    "ExtensionManifest",
    "GuildRateLimiter",
    "RateLimitRule",
    "RateLimitStore",
    "Transport",
    "ViolationRecord",
    "ViolationStore",
    "check_role_assignable",
    "check_role_hierarchy",
    "notify_member_best_effort",
    "rate_limited",
]
