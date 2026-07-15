"""Optional, ready-made commands/event-listeners — the "side dish," not the
main course. `discord_webapi` itself never imports anything under this
package; nothing here runs unless a consumer explicitly imports it and calls
its `setup(bot, ...)` function.

Convention every module in this package follows:

- One self-contained file per command/listener — no package-level registry,
  no auto-discovery, no import-time side effects. `import
  discord_webapi.builtins` on its own registers nothing.
- A single `setup(bot, *, ...)` function that registers the thing on `bot`
  and returns it, so the caller can further decorate it (e.g. with
  `CommandRegistry.command_meta(...)`) or just ignore the return value.
- Every behavioral choice is a keyword argument with a sane default, never
  a hardcoded one — these are starting points, not a mandated shape. Copy
  the file into your own project and edit it however you like; nothing
  here enforces a contract on how your version has to look.
- "Full-featured" over "toy": e.g. `builtins.ban` covers role-hierarchy
  checks, an optional DM before the ban, and a configurable message-deletion
  window — the kind of thing every real moderation bot ends up needing, not
  a bare one-line `guild.ban(member)` wrapper.

See `discord_webapi/builtins/README.md` for the full writeup, including
what's explicitly *not* attempted here yet (a third-party plugin/package
format with its own manifest, versioning, and installer) and why.
"""
