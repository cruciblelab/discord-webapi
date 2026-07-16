# hybrid_moderation

The three moderation systems working together, each in its own lane:

- **automod** *detects* (message checks: banned words, invites, spam, ...)
- **warn** *remembers* (a persistent per-user count)
- **the escalation engine** *decides the punishment* (timeout / kick / ban)

The glue is a few lines of your own code in automod's `on_violation` hook,
which records a warning and records an escalation violation. Crucially:

- automod knows nothing about punishment,
- warn knows nothing about automod,
- and the escalation ladder has **no built-in thresholds** — the server
  owner configures every rung, live, from the dashboard.

Swap any one of the three for your own implementation without touching the
other two. This is the "composable infrastructure, not a monolithic bot"
philosophy made concrete.

## Running it

Same Discord setup as `single_process_bot`. Then:

```bash
pip install -e ".[sql]"
cp examples/hybrid_moderation/.env.example examples/hybrid_moderation/.env
# fill in .env
set -a && source examples/hybrid_moderation/.env && set +a
uvicorn main:app --reload --app-dir examples/hybrid_moderation
```

Configure the ladder (no restart), e.g. timeout at 3 automod hits, kick at 5:

```
PUT /api/guilds/{gid}/escalation-rules/automod/3 {"action": "timeout", "action_minutes": 10}
PUT /api/guilds/{gid}/escalation-rules/automod/5 {"action": "kick"}
```

Add a banned word (edit `BANNED_WORDS` in `main.py`), post it, and watch
automod delete it, a warning get recorded, and the escalation engine act
once the count hits a configured rung.
