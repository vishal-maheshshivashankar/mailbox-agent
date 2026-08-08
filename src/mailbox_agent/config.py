"""Central config loaded from environment / .env."""

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    return default if val is None else val.strip().lower() in ("1", "true", "yes")


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _parse_retention_policy(raw: str) -> dict[str, int]:
    """'promotions:0,social:0,newsletters:365,other:0' -> {'promotions': 0, ...}

    A category's retention days is how old a message must be (by Gmail's
    daily-granularity `before:` search) before the sweep considers it a
    candidate; 0 means "eligible on the very next sweep run" rather than
    truly instantaneous - see docs/ARCHITECTURE.md section 6.

    Categories NOT listed here are structurally invisible to the retention
    sweep - it only ever queries the labels in this dict, so anything absent
    (important, receipts, statements, e_mandate, personal by default) is
    kept forever regardless of age.
    """
    policy = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        category, _, days = entry.partition(":")
        policy[category.strip().lower()] = int(days)
    return policy


# Per-category retention: promotions/social are eligible for deletion
# immediately (no aging period); newsletters wait a year; "other" (mail the
# classifier couldn't confidently place elsewhere) is asked about right
# away via the same Telegram approval flow rather than being kept forever.
RETENTION_POLICY = _parse_retention_policy(
    os.getenv("RETENTION_POLICY", "promotions:0,social:0,newsletters:365,other:0")
)

SORT_INTERVAL_MINUTES = int(os.getenv("SORT_INTERVAL_MINUTES", "20"))
SWEEP_DAY_OF_WEEK = os.getenv("SWEEP_DAY_OF_WEEK", "sun")
SWEEP_HOUR = int(os.getenv("SWEEP_HOUR", "9"))

APPROVAL_TTL_HOURS = int(os.getenv("APPROVAL_TTL_HOURS", "48"))

DRY_RUN = _bool("DRY_RUN", True)

DB_PATH = os.getenv("DB_PATH", "data/app.sqlite3")
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", "data/checkpoints.sqlite3")
GOOGLE_CLIENT_SECRET_PATH = os.getenv("GOOGLE_CLIENT_SECRET_PATH", "secrets/client_secret.json")
TOKENS_DIR = os.getenv("TOKENS_DIR", "secrets/tokens")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ALL_SCOPES = GMAIL_SCOPES + DRIVE_SCOPES

DRIVE_BACKUP_ROOT_FOLDER = os.getenv("DRIVE_BACKUP_ROOT_FOLDER", "EmailCleanerBackups")
