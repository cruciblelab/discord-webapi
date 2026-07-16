"""Discovering installed third-party extensions.

`ExtensionRegistry.discover()` reads the `discord_webapi.extensions` entry
point group (ordinary Python packaging metadata -- `pip install <pkg>` is
the only "installer"), loads each extension's `Extension` object, and
checks its declared `discord_webapi_requires` against the running library
version. It **never runs an extension's `setup`** -- that's always an
explicit host call. The only extension code that runs during discovery is
each package's module import (needed to read its `Extension` object), which
is exactly as much code as `import that_package` would run anyway; by the
`discord_webapi.extras` convention, an extension module has no import-time
side effects.

Trust model: an extension is a normal pip dependency. Installing it is the
trust decision, same as any dependency -- discord-webapi adds no sandbox
and makes no security claim beyond "we don't execute anything you didn't
install and then explicitly call."
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from discord_webapi import __version__
from discord_webapi.extensions.base import Extension

ENTRY_POINT_GROUP = "discord_webapi.extensions"


@dataclass(frozen=True)
class DiscoveredExtension:
    """An `Extension` found on the entry-point group, plus the result of
    checking it against the installed discord-webapi version."""

    extension: Extension
    entry_point_name: str
    compatible: bool
    compat_reason: str | None = None


@dataclass(frozen=True)
class ExtensionLoadError:
    """A `discord_webapi.extensions` entry point that couldn't be turned
    into a usable `Extension` (import raised, pointed at the wrong type, or
    a duplicate name). Collected rather than raised so one broken extension
    never hides every working one."""

    entry_point_name: str
    message: str


def _check_compatible(requires: str | None) -> tuple[bool, str | None]:
    if requires is None:
        return True, None
    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import Version
    except ImportError:
        # `packaging` isn't a hard dependency -- if it's absent we can't
        # evaluate the specifier, so we don't block the extension, we just
        # say the check was skipped.
        return True, "compatibility not checked (packaging not installed)"
    try:
        spec = SpecifierSet(requires)
    except InvalidSpecifier:
        return False, f"invalid discord_webapi_requires specifier {requires!r}"
    installed = Version(__version__)
    if installed in spec:
        return True, None
    return False, (
        f"needs discord-webapi {requires}, but {installed} is installed"
    )


class ExtensionRegistry:
    """Read-only view of the third-party extensions installed in this
    environment. Build one with `ExtensionRegistry.discover()`."""

    def __init__(
        self,
        extensions: list[DiscoveredExtension],
        errors: list[ExtensionLoadError],
    ) -> None:
        self._by_name: dict[str, DiscoveredExtension] = {
            e.extension.manifest.name: e for e in extensions
        }
        self._errors = errors

    @classmethod
    def discover(cls) -> ExtensionRegistry:
        found: list[DiscoveredExtension] = []
        errors: list[ExtensionLoadError] = []
        seen_names: dict[str, str] = {}  # manifest name -> entry point that claimed it

        for ep in entry_points(group=ENTRY_POINT_GROUP):
            discovered = cls._load_one(ep, seen_names, errors)
            if discovered is not None:
                found.append(discovered)
        return cls(found, errors)

    @staticmethod
    def _load_one(
        ep: EntryPoint,
        seen_names: dict[str, str],
        errors: list[ExtensionLoadError],
    ) -> DiscoveredExtension | None:
        try:
            obj = ep.load()
        except Exception as exc:  # noqa: BLE001 -- one bad extension mustn't break discovery
            errors.append(ExtensionLoadError(ep.name, f"failed to import: {exc!r}"))
            return None

        if not isinstance(obj, Extension):
            errors.append(
                ExtensionLoadError(
                    ep.name,
                    f"entry point resolved to {type(obj).__name__}, not a "
                    "discord_webapi.extensions.Extension",
                )
            )
            return None

        name = obj.manifest.name
        if name in seen_names:
            errors.append(
                ExtensionLoadError(
                    ep.name,
                    f"duplicate extension name {name!r} (already provided by "
                    f"entry point {seen_names[name]!r}); ignoring this one",
                )
            )
            return None
        seen_names[name] = ep.name

        compatible, reason = _check_compatible(obj.manifest.discord_webapi_requires)
        return DiscoveredExtension(
            extension=obj,
            entry_point_name=ep.name,
            compatible=compatible,
            compat_reason=reason,
        )

    @property
    def names(self) -> list[str]:
        return sorted(self._by_name)

    @property
    def errors(self) -> list[ExtensionLoadError]:
        return list(self._errors)

    def list(self, *, only_compatible: bool = False) -> list[DiscoveredExtension]:
        items = [self._by_name[n] for n in self.names]
        if only_compatible:
            items = [i for i in items if i.compatible]
        return items

    def get(self, name: str) -> DiscoveredExtension:
        try:
            return self._by_name[name]
        except KeyError:
            available = ", ".join(self.names) or "(none installed)"
            raise KeyError(
                f"no installed extension named {name!r}; available: {available}"
            ) from None
