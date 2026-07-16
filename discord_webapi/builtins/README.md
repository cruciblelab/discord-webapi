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
  same checks three times. Stateless: just a Discord API call + a reply.
- `warn.py` — the first builtin with its own persistent state. Ships a
  `WarnStore` Protocol (`MemoryWarnStore` by default, `SQLWarnStore` behind
  the `discord-webapi[sql]` extra), following the exact same shape as
  `AuditStore`/`ConsentStore` in the core library. `SQLWarnStore` manages
  its own table via its own `create_all()`, entirely independent of
  `discord_webapi.storage.sql.create_all()` — importing `warn.py` never
  creates a table for someone who only wanted `ban.py`. Optional
  auto-timeout escalation after N warnings (`auto_timeout_after=`), off
  by default.
- `welcome.py` — the first non-command builtin: a configurable
  `on_member_join` listener. Same `setup(bot, **kwargs)` shape, proving the
  convention isn't just for slash/hybrid commands. No channel is guessed;
  you pass `channel_id` (or `dm_instead=True`) explicitly.
- `role_assign.py` — `/role-add`/`/role-remove` commands. Stateless, same
  role-hierarchy philosophy as `ban.py`/`kick.py`/`timeout.py`, but checks
  the *role being granted/removed* rather than a target member's rank
  (`_shared.check_role_assignable`) -- Discord enforces `MANAGE_ROLES`
  hierarchy against the bot's own rank when a bot token makes the call,
  not the invoking human's, so this needs its own client-side guard for
  the same reason the member-targeting commands do.
- `automod.py` — the second non-command builtin: a configurable
  `on_message` listener with an independent banned-word filter and a
  simple message-rate spam filter. Neither escalates to a ban/kick/timeout
  or keeps a persistent strike count (that's `warn.py`'s job) -- this only
  ever deletes a message and optionally posts a short in-channel notice.
  Both checks are in-memory only, same "an evicted/reset counter is
  harmless" reasoning as `commands.ratelimit.TokenBucketLimiter`.

Every database/cache/permission concern above stays a separate,
composable piece — use one function from `_shared.py`, one whole builtin,
swap `MemoryWarnStore` for your own `WarnStore`, or write the entire
command from scratch. None of it is an all-or-nothing package.

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
