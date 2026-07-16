"""`python -m discord_webapi.extensions.scaffold new <name> [--dir DIR]`

Generates a convention-following, immediately-installable skeleton
extension package so an author starts from a working `pip install -e .`
+ discoverable extension rather than a blank file. The generated package
registers a tiny example `/roll` command built on the SDK, declares its
`discord_webapi.extensions` entry point, and ships a passing test.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PYPROJECT = '''\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# Templates use __TOKEN__ placeholders (not str.format) so the generated
# f-string braces (e.g. {random.randint(...)}) survive untouched.

[project]
name = "__DIST__"
version = "0.1.0"
description = "A discord-webapi extension."
requires-python = ">=3.11"
dependencies = ["discord-webapi>=0.6"]

# This is what makes the package discoverable by ExtensionRegistry.discover().
[project.entry-points."discord_webapi.extensions"]
__PKG__ = "__PKG__:extension"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24"]

[tool.hatch.build.targets.wheel]
packages = ["__PKG__"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
'''

_INIT = '''\
"""The __PKG__ discord-webapi extension."""

from discord_webapi.extensions.sdk import Extension, ExtensionManifest

from __PKG__.commands import setup

extension = Extension(
    manifest=ExtensionManifest(
        name="__NAME__",
        version="0.1.0",
        description="A discord-webapi extension.",
        discord_webapi_requires=">=0.6,<1.0",
        provides=["command:roll"],
    ),
    setup=setup,
)

__all__ = ["extension", "setup"]
'''

_COMMANDS = '''\
"""The actual behavior. Built against discord_webapi.extensions.sdk only --
exactly the same public surface discord-webapi's own `extras` use, so this
extension is architecturally identical to a first-party one."""

from __future__ import annotations

import random
from typing import Any

from discord.ext import commands

from discord_webapi.extensions.sdk import GuildRateLimiter, rate_limited


def setup(bot: commands.Bot, *, rate_limiter: GuildRateLimiter | None = None) -> Any:
    """Registers a `/roll` command on `bot`.

    Pass the host application's `api.rate_limiter` as `rate_limiter` to make
    the command per-guild rate-limitable from the dashboard (key "roll");
    omit it and the command simply isn't rate limited. This is the standard
    "the host injects its infrastructure" convention -- see
    docs/PAKET_YAZMA.md.
    """

    @bot.hybrid_command(name="roll", description="Roll a six-sided die")
    @rate_limited("roll", rate_limiter=rate_limiter)
    async def roll(ctx: commands.Context) -> None:
        await ctx.reply(f"You rolled a {random.randint(1, 6)}.")

    return roll
'''

_TEST = '''\
from types import SimpleNamespace

import discord
from discord.ext import commands as dpy_commands

from __PKG__.commands import setup


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


async def test_roll_replies_with_a_number() -> None:
    bot = _build_bot()
    command = setup(bot)
    replies = []

    async def reply(msg):
        replies.append(msg)

    ctx = SimpleNamespace(guild=None, author=SimpleNamespace(id=1), reply=reply)

    await command.callback(ctx)

    assert replies and "rolled" in replies[0]
'''

_README = '''\
# __DIST__

A [discord-webapi](https://github.com/cruciblelab/discord-webapi) extension.

## Install

    pip install -e .

Once installed it's discoverable by any discord-webapi host:

```python
from discord_webapi.extensions import ExtensionRegistry

reg = ExtensionRegistry.discover()
ext = reg.get("__NAME__")
if ext.compatible:
    ext.extension.setup(bot, rate_limiter=api.rate_limiter)
```

Or import it directly, like any package:

```python
from __PKG__.commands import setup as setup_roll
setup_roll(bot, rate_limiter=api.rate_limiter)
```
'''


def _sanitize_pkg(name: str) -> str:
    pkg = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip().lower())
    if not pkg or pkg[0].isdigit():
        pkg = f"ext_{pkg}"
    return pkg


def _render(template: str, *, name: str, pkg: str, dist: str) -> str:
    return (
        template.replace("__NAME__", name).replace("__PKG__", pkg).replace("__DIST__", dist)
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_extension(name: str, target_dir: Path) -> Path:
    """Writes a skeleton extension package for `name` under `target_dir`,
    returning the created project root. Raises `FileExistsError` if the
    project directory already exists (never overwrites)."""
    pkg = _sanitize_pkg(name)
    dist = name.strip().lower().replace("_", "-").replace(" ", "-")
    root = target_dir / dist
    if root.exists():
        raise FileExistsError(f"{root} already exists")

    clean_name = name.strip()
    _write(root / "pyproject.toml", _render(_PYPROJECT, name=clean_name, pkg=pkg, dist=dist))
    _write(root / pkg / "__init__.py", _render(_INIT, name=clean_name, pkg=pkg, dist=dist))
    _write(root / pkg / "commands.py", _render(_COMMANDS, name=clean_name, pkg=pkg, dist=dist))
    _write(root / "tests" / f"test_{pkg}.py", _render(_TEST, name=clean_name, pkg=pkg, dist=dist))
    _write(root / "README.md", _render(_README, name=clean_name, pkg=pkg, dist=dist))
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m discord_webapi.extensions.scaffold",
        description="Scaffold a discord-webapi extension package.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Create a new extension skeleton.")
    new.add_argument("name", help="Extension name, e.g. 'funbot'.")
    new.add_argument(
        "--dir", default=".", help="Directory to create the project in (default: cwd)."
    )
    args = parser.parse_args(argv)

    if args.command == "new":
        try:
            root = create_extension(args.name, Path(args.dir))
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Created extension skeleton at {root}")
        print("Next: cd into it, `pip install -e .`, then it's discoverable.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
