# discord-webapi

FastAPI + discord.py glue for building Discord bot web dashboards: OAuth2
login, guild-role authorization, and a live bot-to-dashboard command bridge.

Status: early development (v0.1 core).

## Why

Building an admin dashboard for a Discord bot means writing the same
boilerplate every time: Discord OAuth2 login, guild-role permission checks,
and some ad-hoc way to expose the bot's commands to a web panel.
discord-webapi turns that into a small, opinionated layer on top of FastAPI
and discord.py — a narrow "bot + dashboard" framework, not a competitor to
either.

## Install

```bash
pip install discord-webapi[sql]   # or [redis], or [all]
```

See `examples/single_process_bot/` for a runnable end-to-end example.
