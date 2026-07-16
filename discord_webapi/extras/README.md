# `discord_webapi.extras`

Everything in this package is optional — the "side dish," not the main
course. The library's actual job is the bot↔dashboard bridge (auth,
authz, live command config, Transport, `ratelimits`, `escalation`); it
isn't trying to be your bot's moderation logic. `extras` holds two
different depths of optional building block, both entirely opt-in
(`import discord_webapi` never pulls in anything from here):

- **Full commands** (this directory): complete, production-quality,
  fully-configurable commands and listeners you can use as-is — `ban.py`,
  `kick.py`, `timeout.py`, `warn.py`, `welcome.py`, `role_assign.py`,
  `automod/`. Real DM notices, role-hierarchy checks, persistent
  stores — the whole thing, one `setup(bot, **kwargs)` call away.
- **Skeletons** (`skeletons/`, see [its own README](skeletons/README.md)):
  the opposite depth — a thin decorator that wires up just the
  infrastructure (a rate-limit check, say) and leaves *everything* the
  command actually does to you. "Rebar, not a finished wall." Use these
  when a full command is more than you want and you'd rather write the
  body yourself but skip re-wiring the same rate-limit/dashboard-config
  boilerplate every time.

Neither depth is "better" — they're different tools for different
amounts of control. A full command is one line for the common case; a
skeleton is for when you want to keep writing your own command bodies
but stop repeating the same infrastructure glue.

## Convention

- **One file (or one subpackage) per command/listener.** No
  package-level registry, no auto-discovery. `import discord_webapi.extras`
  registers nothing by itself — nothing runs until you explicitly import
  a specific module and call its `setup(bot, ...)` (full commands) or use
  its decorator (skeletons).
- **`setup(bot, *, ...)` returns the registered object** (full commands).
  So you can chain it into `CommandRegistry.command_meta(...)` or ignore
  the return value.
- **Every behavior is a keyword argument**, never hardcoded. `ban.py`,
  for example, lets you turn off the required-reason check, the pre-ban
  DM, or change the default message-deletion window — nothing is a "take
  it or leave it" default.
- **Self-contained.** No file in here depends on another in a way that
  would surprise you — `automod` never imports `warn`, `ban`/`kick`/
  `timeout` all reuse `_shared.py`'s role-hierarchy check rather than each
  other. This is also what makes the convention itself third-party-
  friendly: nothing stops someone else writing a `setup(bot, **kwargs)`
  module of their own, following the same shape, and sharing it — it
  doesn't need our permission or a plugin system to "just work" the same
  way any of these do. (A proper packaged/installable version of that —
  manifests, versioning, a resolver — is a bigger, deliberately deferred
  project; see the note at the bottom of this file.)

## Full commands

```python
from discord_webapi.extras.ban import setup as setup_ban

ban_command = setup_ban(bot, require_reason=False, dm_before_ban=False)
registry.command_meta(category="moderation")(ban_command)
```

- `_shared.py` — role-hierarchy checks and best-effort DM delivery, factored
  out because every moderation command needs them. Import just this if
  you're writing your own command from scratch and only want the
  hierarchy check, not a whole prebuilt command.
- `ban.py`, `kick.py`, `timeout.py` — each a self-contained `setup(bot,
  **kwargs)`, each reusing `_shared.py` rather than re-implementing the
  same checks three times. Stateless: just a Discord API call + a reply.
- `warn.py` — the first one with its own persistent state. Ships a
  `WarnStore` Protocol (`MemoryWarnStore` by default, `SQLWarnStore` behind
  the `discord-webapi[sql]` extra), following the exact same shape as
  `AuditStore`/`ConsentStore` in the core library. `SQLWarnStore` manages
  its own table via its own `create_all()`, entirely independent of
  `discord_webapi.storage.sql.create_all()` — importing `warn.py` never
  creates a table for someone who only wanted `ban.py`. Optional
  auto-timeout escalation after N warnings (`auto_timeout_after=`), off
  by default.
- `welcome.py` — the first non-command one: a configurable
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
- `automod/` — the second non-command one, and the first that's a
  whole subpackage rather than a single file: a coordinator
  (`automod/__init__.py::setup()`) wiring together seven independent,
  individually importable checks, each its own module:
  - `banned_words.py` — case-insensitive, whole-word filter.
  - `spam.py` — message-rate limiting (in-memory sliding window, same
    "an evicted/reset counter is harmless" reasoning as
    `commands.ratelimit.TokenBucketLimiter`).
  - `mention_spam.py` — mass-mention/raid protection.
  - `invite_filter.py` — blocks other servers' Discord invite links
    (with an allowlist for specific codes).
  - `link_filter.py` — generic URL domain allowlist/blocklist,
    independent of the invite filter.
  - `caps_spam.py` — excessive-caps ("SHOUTING") detection.
  - `emoji_spam.py` — excessive custom/Unicode emoji detection.
  - `exemptions.py` — who's skipped entirely (moderators with
    `manage_messages` by default, plus configured role/channel
    exemptions), applied once before any check runs.

  Every check is a pure, synchronous, side-effect-free function of a
  `discord.Message` (`Callable[[discord.Message], str | None]`, see
  `automod/base.py`) -- no `await`, no I/O, trivially unit-testable with a
  plain fake message object. `setup()` is the only thing that touches
  Discord: it runs the enabled checks in order, stops at the first
  violation, then deletes the message / posts a short in-channel notice /
  posts a permanent log-channel entry / awaits your own `on_violation`
  callback -- any combination, all independently toggleable. `automod`
  never escalates to a ban/kick/timeout or keeps a persistent strike count
  itself (that's `warn.py`'s job, or better yet, `discord_webapi.escalation`
  -- see `examples/full_featured_bot/main.py` for `on_violation=` wired
  straight into an `EscalationEngine`).

Every database/cache/permission concern above stays a separate,
composable piece — use one function from `_shared.py`, one whole command,
swap `MemoryWarnStore` for your own `WarnStore`, or write the entire
command from scratch. None of it is an all-or-nothing package.

## Skeletons

See [`skeletons/README.md`](skeletons/README.md) for the full convention
and a ten-scenario deep dive (dashboard-driven customization, writing to
your own database, opting out entirely, combining with `EscalationEngine`,
per-guild independent config, sharing one handler between prefix and
slash commands, permission-gate stacking, shared quotas across commands,
localized replies, and running against a SQL-backed store).

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
bolted onto this one. The convention above (self-contained, no hidden
dependencies, `setup(bot, **kwargs)` or a plain decorator) is deliberately
already compatible with that future without needing to change.
