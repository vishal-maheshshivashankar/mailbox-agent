# Mailbox Sort & Cleanup Agent

LangGraph agent that labels mail across your Gmail accounts and, per a
configurable per-category retention policy, backs up and retires low-value
mail after you approve it via Telegram.

Full architecture and rationale: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
How classification quality is measured: [docs/EVALUATION.md](docs/EVALUATION.md).

**Status**: personal project, not published or licensed for reuse/redistribution.

## What you need before running this

1. **A Google Cloud OAuth client** (free) — this is what lets the app talk to
   your Gmail/Drive accounts.
   - Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project.
   - APIs & Services → Library → enable **Gmail API** and **Google Drive API**.
   - APIs & Services → OAuth consent screen → External → fill in app name/email
     → add your Gmail addresses as **test users** (required while the app is
     unverified — fine for personal use, no Google review needed).
   - APIs & Services → Credentials → Create Credentials → OAuth client ID →
     type **Desktop app** → download the JSON.
   - Save it as `secrets/client_secret.json` in this project.

2. **A Gemini API key** (free tier available) — [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

3. **A Telegram bot**:
   - Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
   - Message your new bot once (anything), then open in a browser:
     `https://api.telegram.org/bot<TOKEN>/getUpdates` and read off your
     `chat.id` — that's your `TELEGRAM_CHAT_ID`.

## Setup

This is an installable package (`src/` layout) rather than a folder of
loose scripts — `pip install -e .` makes `mailbox_agent` importable from
anywhere and gives you the CLI commands below regardless of your current
directory.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable install + pytest/ruff/mypy

cp .env.example .env
# edit .env: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

## Onboard each Gmail account

Runs a one-time OAuth consent flow per account (opens a browser):

```bash
mailbox-agent-add-account --id personal --email you@gmail.com
mailbox-agent-add-account --id work --email you@work-domain.com
```

Tokens are stored per-account under `secrets/tokens/` — never commit `secrets/`.

## Run it

Everything — scheduled sort loop, scheduled retention sweep, Telegram
approval listener — in one process:

```bash
mailbox-agent-serve
```

- Sort loop runs every `SORT_INTERVAL_MINUTES` (default 20) per account:
  fetches new mail, classifies it with Gemini, applies labels
  (`AI/Important`, `AI/Promotions`, `AI/Social`, `AI/Newsletters`,
  `AI/Receipts`, `AI/Statements`, `AI/E-Mandate`, `AI/Personal`,
  `AI/Other`). Never deletes anything.
- Retention sweep runs weekly (`SWEEP_DAY_OF_WEEK`/`SWEEP_HOUR`): finds mail
  matching `RETENTION_POLICY` (per-category age thresholds — default:
  Promotions/Social/Other eligible immediately, Newsletters after 365 days;
  Important/Personal/Receipts/Statements/E-Mandate are never touched, at any
  age), and:
  - **while `DRY_RUN=true` (the default)**: only sends you a Telegram report
    of what it *would* do — no backup, no delete.
  - **once you set `DRY_RUN=false`**: backs the messages up to Drive
    (`EmailCleanerBackups/<account>/<year>/backup_*.zip`), then messages you
    on Telegram with Approve/Reject buttons. Nothing is deleted until you
    tap Approve, and even then it only goes to Gmail Trash (30-day recovery
    window), never permanent delete.
  - unanswered requests auto-expire after `APPROVAL_TTL_HOURS` (default 48)
    and re-queue for the next sweep — nothing is left hanging.

**Recommended first run**: leave `DRY_RUN=true`, let a sort loop and a sweep
run, check the Telegram reports and the `AI/*` labels in Gmail match what you
expect, *then* flip to `DRY_RUN=false`.

Logs are structured JSON by default (set `LOG_FORMAT=text` in `.env` for
plain text while developing locally).

## Mark VIP senders (never touched by retention/deletion)

```python
python -c "from mailbox_agent.toolkit import rules; rules.add_vip('personal', 'important-person@example.com')"
```

## Manual/inspection console (optional, MCP)

`mailbox_agent/mcp_server/server.py` exposes the same toolkit as MCP tools
(`preview_retention_candidates`, `list_pending_approvals`,
`resolve_approval_manually`, `add_vip_sender`, …) so you can inspect or
override things from Claude Desktop/Code instead of only Telegram — see
docs/ARCHITECTURE.md section 8 for why this is a thin, secondary wrapper rather
than the primary path.

```bash
python -m mailbox_agent.mcp_server.server
```

## Run one thing manually (without the scheduler)

```bash
mailbox-agent-sort --account personal
mailbox-agent-sweep --account personal
mailbox-agent-telegram-bot   # just the approval listener
```

## Development

```bash
make check    # ruff lint + mypy + unit tests - run before every commit
make test     # unit tests only (fast, no network, no real credentials)
make test-eval  # classification quality eval against the real Gemini API (costs money)
make format   # auto-format with ruff
```

Or `pre-commit install` once, and `make check`'s pieces run automatically on
every `git commit` (see `.pre-commit-config.yaml`).

CI (`.github/workflows/ci.yml`) runs lint/types/unit-tests on every push and
PR. The classification eval (`.github/workflows/eval.yml`) is deliberately
**manual-trigger only** — it calls the real Gemini API and costs money per
run, which is the wrong default for a required check on every commit. See
[docs/EVALUATION.md](docs/EVALUATION.md) for the full reasoning and how to grow the
eval dataset from your own mailbox.

## Project layout

```
pyproject.toml         package metadata, deps, ruff/mypy/pytest config
src/mailbox_agent/
  toolkit/              Gmail/Drive/Telegram/Gemini functions - no LangGraph here
    retry.py            tenacity retry policies for external API calls
  graphs/               the two LangGraph graphs (sort_loop, retention_sweep) + state
  scripts/              entrypoints (add_account, run_sort, run_sweep, telegram_bot)
  eval/                 golden dataset + eval runner (see docs/EVALUATION.md)
  mcp_server/           optional MCP wrapper around toolkit/ for manual use
  db/                   SQLite schema + accessors (accounts, audit_log, pending_approvals, sender_rules)
  logging_config.py     structured JSON logging setup
  scripts/serve.py      runs everything together: scheduler + Telegram listener (Docker CMD)
tests/
  unit/                 fast, mocked, no network - runs in default `pytest`
  eval/                 real-API classification quality check - `pytest -m eval` only
docs/                   ARCHITECTURE.md, EVALUATION.md
Dockerfile, docker-compose.yml, .dockerignore
.github/workflows/      GitHub Actions CI (lint/types/tests + manual eval job)
.gitlab-ci.yml          GitLab CI equivalent (lint/types/tests)
```

## Data stores

- `data/app.sqlite3` — accounts, audit log, pending approvals, learned
  sender rules. Back this up (it's the audit trail).
- `data/checkpoints.sqlite3` — LangGraph run state, including paused
  retention-sweep threads waiting on your Telegram tap.

Both are SQLite by design at this scale (2-5 accounts) — see
docs/ARCHITECTURE.md section 10 for the Postgres migration path if that changes.

## Releasing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(enforced by the `commitizen` pre-commit hook — `pre-commit install --hook-type commit-msg`
once, in addition to the usual `pre-commit install`). Cutting a release:

```bash
cz bump          # reads commit history, bumps version in pyproject.toml,
                  # updates CHANGELOG.md, commits, tags e.g. v0.2.0
git push && git push --tags
```

Pushing a `vX.Y.Z` tag triggers `.github/workflows/docker-publish.yml`,
which builds the image from the `Dockerfile` and pushes
`ghcr.io/vishal-maheshshivashankar/mailbox-agent:X.Y.Z` and `:latest` to
GitHub Container Registry.

## Deployment (Oracle VM via Docker Compose)

The VM never builds the image — it only pulls what CI already published to
GHCR and restarts the container. One-time setup on the VM:

```bash
# install docker + the compose plugin (Ubuntu example)
curl -fsSL https://get.docker.com | sh
sudo apt-get install -y docker-compose-plugin

git clone https://github.com/vishal-maheshshivashankar/mailbox-agent.git
cd mailbox-agent
cp .env.example .env        # fill in real values
mkdir -p secrets/tokens
# copy secrets/client_secret.json and secrets/tokens/*.json over from a
# trusted channel (scp) - never commit these
```

Every time you want the VM running a new version, after `cz bump` has
published a new image:

```bash
git pull                          # picks up docker-compose.yml changes, if any
IMAGE_TAG=0.2.0 docker compose pull
IMAGE_TAG=0.2.0 docker compose up -d
```

Or persist the tag by adding `IMAGE_TAG=0.2.0` to `.env` instead of passing
it inline each time. Omitting `IMAGE_TAG` pulls `:latest`.

Because the repo is public, GHCR image pulls need no authentication on the
VM. If you ever flip the repo private, `docker login ghcr.io -u <user>`
with a PAT that has `read:packages` scope first.
