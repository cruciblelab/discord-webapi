"""The object a third-party extension package exposes at its entry point.

The whole "plugin" contract is deliberately this small: a package declares
one `Extension` (a manifest + a `setup` callable) and points a
`discord_webapi.extensions` entry point at it. That's it. There is no
plugin runtime, no sandbox, no privileged API -- the extension's `setup`
is an ordinary callable the *host application* invokes explicitly (never
discord-webapi itself, never at import/discovery time), and it builds
against the same public surface (`discord_webapi.extensions.sdk`) our own
`extras` use. A third-party extension is architecturally indistinguishable
from a first-party one; this module just gives it a name tag and a front
door so hosts can find it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from discord_webapi.extensions.manifest import ExtensionManifest


@dataclass(frozen=True)
class Extension:
    """What a package assigns to its `discord_webapi.extensions` entry point.

    `setup` is whatever callable the host runs to install the extension --
    by convention `setup(bot, **kwargs)`, matching `discord_webapi.extras`,
    but its exact signature is the extension's own business (a full bot
    infrastructure might take `setup(bot, *, rate_limiter=..., ...)` and be
    handed the host's `DiscordWebAPI.rate_limiter`/`escalation_engine`).
    discord-webapi never calls `setup` itself -- it only ever hands it back
    to the host, which calls it with whatever that extension documents.
    """

    manifest: ExtensionManifest
    setup: Callable[..., Any]
