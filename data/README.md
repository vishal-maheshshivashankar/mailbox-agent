# data/

Runtime state, gitignored (everything except this file — see `.gitignore`).
Created automatically on first run; nothing here needs to be created by hand.

- `app.sqlite3` — accounts, audit log, pending approvals, learned sender
  rules. This is the audit trail; back it up.
- `checkpoints.sqlite3` — LangGraph run state, including any retention-sweep
  thread currently paused waiting on a Telegram approval.

In Docker, this directory is bind-mounted (`docker-compose.yml`) so state
survives container rebuilds. See `docs/ARCHITECTURE.md` section 10 for why
SQLite rather than a database server at this project's scale.
