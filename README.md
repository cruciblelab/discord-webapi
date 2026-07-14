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

Every route works the same for a browser dashboard, a mobile app, or a
third-party API/SaaS client — auth uses one opaque session that a request
can present either as an httpOnly cookie (browser) or an
`Authorization: Bearer <session_id>` header (mobile apps, server-to-server
integrations, anything else). See `DiscordAuth`'s docstring in
`discord_webapi/auth/oauth.py` for the mobile login handshake
(`/login?mobile=true` + `mobile_redirect_uri`).

## Install

```bash
pip install discord-webapi[sql]   # or [redis], or [all]
```

See `examples/single_process_bot/` for a runnable end-to-end example.
