# secrets/

Credentials, gitignored (everything except this file — see `.gitignore`).
**Never commit anything else in this directory.**

- `client_secret.json` — OAuth client downloaded from Google Cloud Console
  (APIs & Services → Credentials → OAuth client ID → Desktop app). One
  client is shared across all onboarded Gmail accounts. See `README.md` at
  the project root for the full setup walkthrough.
- `tokens/<account_id>.json` — per-account OAuth tokens, created
  automatically by `mailbox-agent-add-account`. One file per onboarded
  Gmail account.

In Docker, this directory is bind-mounted (`docker-compose.yml`) so tokens
survive container rebuilds.
