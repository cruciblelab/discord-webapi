# `discord_webapi.builtins`

Ready-made, fully-configurable commands and (soon) Gateway event listeners —
the "side dish," not the main course. This library's job is the
bot↔dashboard bridge (auth, authz, live command config, transport); it isn't
trying to be your bot's moderation logic. What's here is a set of real,
production-quality building blocks you can take as-is, tweak via keyword
arguments, or copy into your own project and edit freely.

## Convention

- **One file per command/listener.** No package-level registry, no
  auto-discovery. `import discord_webapi.builtins` registers nothing by
  itself — nothing runs until you explicitly import a specific module and
  call its `setup(bot, ...)`.
- **`setup(bot, *, ...)` returns the registered object.** So you can chain
  it into `CommandRegistry.command_meta(...)` or ignore the return value.
- **Every behavior is a keyword argument**, never hardcoded. `builtins.ban`,
  for example, lets you turn off the required-reason check, the pre-ban DM,
  or change the default message-deletion window — nothing is a "take it or
  leave it" default.
- **Full-featured, not a toy.** `builtins.ban` isn't a five-line
  `guild.ban(member)` wrapper — it layers role-hierarchy checks on top of
  Discord's own, a best-effort DM notice, and a configurable
  message-deletion window, because that's what a real moderation bot
  actually ends up needing. The point is that you write one line
  (`setup_ban(bot)`) to get the full thing, or 20-50 lines if you want to
  wrap/extend it with your own project-specific behavior on top.

## Example

```python
from discord_webapi.builtins.ban import setup as setup_ban

ban_command = setup_ban(bot, require_reason=False, dm_before_ban=False)
registry.command_meta(category="moderation")(ban_command)
```

## What's here so far

- `_shared.py` — role-hierarchy checks and best-effort DM delivery, factored
  out because every moderation command needs them. Import just this if
  you're writing your own command from scratch and only want the
  hierarchy check, not a whole prebuilt command.
- `ban.py`, `kick.py`, `timeout.py` — each a self-contained `setup(bot,
  **kwargs)`, each reusing `_shared.py` rather than re-implementing the
  same checks three times.

More builtins (warn, plus Gateway event listeners like `on_member_join`
welcome messages) will land the same way: one file, one `setup()`, no
forced adoption. Anything needing its own persistent state (e.g. a warn
counter) gets its own `Store` protocol + Memory/SQL pair — same shape as
`AuditStore`/`ConsentStore` — so database/cache/permission concerns stay
separable pieces you can use individually, replace, or skip, exactly like
everything else in this library.

## What this is explicitly *not* (yet)

A larger idea came up while planning this: a proper third-party
plugin/package format — a `.json` manifest per package (name, version,
author, dependencies), something that could be published and installed
almost like a mini app store for bot commands, with a build/install step
that "just works" once dropped into a project. That's a real and
potentially valuable direction, but it's a different, much bigger project
(package format design, a resolver/installer, security review for
running third-party code, versioning policy) than "ship a well-written ban
command." It's intentionally deferred — same category as the "extension /
structure system" already noted as a v0.3+/"after core is frozen" idea in
the original architecture plan — not because it isn't wanted, but because
building it well needs its own dedicated design pass rather than being
bolted onto this one.
