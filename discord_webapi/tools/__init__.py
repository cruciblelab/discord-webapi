"""Terminal-based operator tools -- things you *run*, not things you
import into a bot. Kept separate from `discord_webapi.extras` (bot
behavior) and the core packages (`storage`, `escalation`, ...) on purpose:
different audience, different usage pattern (a one-off CLI invocation,
not a `setup(bot, ...)` call).

- `discord_webapi.tools.migrate`: move all data from one SQL database to
  another (e.g. SQLite -> MariaDB), with an automatic pre-migration
  checkpoint so a bad migration can be undone.
"""
