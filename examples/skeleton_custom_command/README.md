# skeleton_custom_command

The "rebar, not a finished wall" use case in one focused file: you write
your own command from scratch, and use discord-webapi *only* for the
repetitive infrastructure — a per-guild, dashboard-configurable rate limit
— via the `rate_limited` skeleton decorator.

discord-webapi never decides what `/weather` replies with. You do. It just
wires the rate-limit check so you don't rewrite that boilerplate for every
command, and makes it configurable per server, live, from the dashboard.

See `discord_webapi/extras/skeletons/README.md` for the full ten-scenario
deep dive; this is the minimal runnable version of scenario 1 + a custom
`rate_limit_key`.

## Running it

Same as `single_process_bot` — see that example's README for the Discord
setup. Then:

```bash
pip install -e ".[sql]"
cp examples/skeleton_custom_command/.env.example examples/skeleton_custom_command/.env
# fill in .env
set -a && source examples/skeleton_custom_command/.env && set +a
uvicorn main:app --reload --app-dir examples/skeleton_custom_command
```

Configure the rate limit for one guild, live, no restart:

```
PUT /api/guilds/{guild_id}/ratelimits/weather {"max_calls": 1, "per_seconds": 30}
```
