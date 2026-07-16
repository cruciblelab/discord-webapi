"""Third-party extension discovery -- a lightweight "share a full bot
infrastructure as a pip package" convention, deliberately *not* a plugin
runtime.

- Write an extension: see `discord_webapi.extensions.sdk` (the stable API
  you build against) and `docs/PAKET_YAZMA.md`. You declare one
  `Extension` (a `manifest` + a `setup` callable) and point a
  `discord_webapi.extensions` entry point at it in your `pyproject.toml`.
- Use installed extensions: `ExtensionRegistry.discover()` lists what's
  `pip install`ed, checks version compatibility, and hands each extension's
  `setup` back to you to call explicitly. discord-webapi never runs an
  extension's `setup` on its own.

The scaffold CLI (`python -m discord_webapi.extensions.scaffold new <name>`)
generates a convention-following skeleton package to start from.
"""

from discord_webapi.extensions.base import Extension
from discord_webapi.extensions.manifest import ExtensionManifest
from discord_webapi.extensions.registry import (
    ENTRY_POINT_GROUP,
    DiscoveredExtension,
    ExtensionLoadError,
    ExtensionRegistry,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "DiscoveredExtension",
    "Extension",
    "ExtensionLoadError",
    "ExtensionManifest",
    "ExtensionRegistry",
]
