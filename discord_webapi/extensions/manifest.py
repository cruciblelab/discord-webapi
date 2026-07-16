"""What a third-party extension declares about itself.

This is *metadata only* -- it never grants an extension any special access
to discord-webapi's internals. An extension is an ordinary pip package that
builds against the same public surface (`discord_webapi.extensions.sdk`)
our own `extras` use; the manifest just lets a host application discover
what's installed, show it in a list, and check version compatibility
before calling the extension's `setup()`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtensionManifest(BaseModel):
    """Declared by a third-party extension package. See
    `docs/PAKET_YAZMA.md` for the authoring guide.

    None of these fields give an extension elevated privileges -- they're
    purely informational (plus `discord_webapi_requires`, which is checked
    against the installed library version at discovery time so an extension
    written for an incompatible version surfaces as a clear error rather
    than a confusing runtime failure deep inside its `setup()`).
    """

    name: str = Field(
        description="Unique, importable-style short name, e.g. 'funbot'. "
        "Used as the key in ExtensionRegistry.get(name)."
    )
    version: str = Field(description="The extension's own version, e.g. '1.2.0'.")
    author: str | None = Field(default=None, description="Who wrote/maintains it.")
    description: str | None = Field(
        default=None, description="One line on what it provides."
    )
    discord_webapi_requires: str | None = Field(
        default=None,
        description="PEP 440 version specifier for the discord-webapi versions this "
        "extension supports, e.g. '>=0.6,<1.0'. Checked against the installed version "
        "at discovery. None means 'no declared constraint' (checked as always-compatible).",
    )
    homepage: str | None = Field(
        default=None, description="Where to read more / report issues."
    )
    provides: list[str] = Field(
        default_factory=list,
        description="Informational list of what this extension offers, e.g. "
        "['command:8ball', 'command:trivia', 'listener:levelup']. Purely for humans "
        "browsing a registry -- discord-webapi never acts on these strings.",
    )
