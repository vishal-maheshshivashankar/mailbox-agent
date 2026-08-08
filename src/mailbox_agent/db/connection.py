"""SQLite connection + audit/rules/approvals helpers.

SQLite (not Postgres) is a deliberate choice at this scale: 2-5 accounts and a
few thousand emails/month don't need a database server. See docs/ARCHITECTURE.md
section 10 for the Postgres migration path if this ever needs multi-worker
scale.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from mailbox_agent import config

_LOCK = threading.Lock()
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with open(_SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def _get_conn() -> sqlite3.Connection:
    # Lazy on purpose: importing this module must not have side effects
    # (opening a file, creating tables) - only actually using the DB should.
    # This also makes the module testable: point config.DB_PATH at a temp
    # file, call reset_connection(), and the next call opens a fresh one.
    global _conn
    if _conn is None:
        _conn = _connect()
    return _conn


def reset_connection() -> None:
    """Test-only: close the cached connection so the next call re-opens one
    against the current config.DB_PATH."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


@contextmanager
def db_lock():
    """All writers share one lock; fine at this volume, avoids sqlite lock errors."""
    with _LOCK:
        yield _get_conn()


def add_account(account_id: str, email: str) -> None:
    with db_lock() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (id, email) VALUES (?, ?)",
            (account_id, email),
        )
        conn.commit()


def list_accounts() -> list[sqlite3.Row]:
    with db_lock() as conn:
        return conn.execute("SELECT * FROM accounts").fetchall()


def write_audit_log(account_id: str, run_id: str, action: str, message_ids: list[str], detail: dict) -> None:
    with db_lock() as conn:
        conn.execute(
            "INSERT INTO audit_log (account_id, run_id, action, message_ids, detail) VALUES (?, ?, ?, ?, ?)",
            (account_id, run_id, action, json.dumps(message_ids), json.dumps(detail)),
        )
        conn.commit()


def create_pending_approval(approval_id: str, account_id: str, thread_id: str, summary: dict) -> None:
    with db_lock() as conn:
        conn.execute(
            "INSERT INTO pending_approvals (id, account_id, thread_id, summary) VALUES (?, ?, ?, ?)",
            (approval_id, account_id, thread_id, json.dumps(summary)),
        )
        conn.commit()


def resolve_pending_approval(approval_id: str, status: str) -> sqlite3.Row | None:
    with db_lock() as conn:
        row = conn.execute("SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE pending_approvals SET status = ?, resolved_at = datetime('now') WHERE id = ?",
            (status, approval_id),
        )
        conn.commit()
        return row


def get_expired_pending_approvals(ttl_hours: int) -> list[sqlite3.Row]:
    with db_lock() as conn:
        return conn.execute(
            "SELECT * FROM pending_approvals WHERE status = 'pending' AND created_at <= datetime('now', ?)",
            (f"-{ttl_hours} hours",),
        ).fetchall()


def get_sender_rule(account_id: str, sender: str) -> sqlite3.Row | None:
    with db_lock() as conn:
        return conn.execute(
            "SELECT * FROM sender_rules WHERE account_id = ? AND sender = ?",
            (account_id, sender),
        ).fetchone()


def upsert_sender_rule(account_id: str, sender: str, category: str, auto_delete: bool = False) -> None:
    with db_lock() as conn:
        conn.execute(
            """INSERT INTO sender_rules (account_id, sender, category, auto_delete, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(account_id, sender) DO UPDATE SET
                 category=excluded.category, auto_delete=excluded.auto_delete, updated_at=excluded.updated_at""",
            (account_id, sender, category, int(auto_delete)),
        )
        conn.commit()


def is_vip_sender(account_id: str, sender: str) -> bool:
    with db_lock() as conn:
        row = conn.execute(
            "SELECT 1 FROM vip_senders WHERE account_id = ? AND sender = ?",
            (account_id, sender),
        ).fetchone()
        return row is not None


def add_vip_sender(account_id: str, sender: str) -> None:
    with db_lock() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vip_senders (account_id, sender) VALUES (?, ?)",
            (account_id, sender),
        )
        conn.commit()


def get_last_sort_at(account_id: str) -> str | None:
    with db_lock() as conn:
        row = conn.execute(
            "SELECT last_sort_at FROM sync_state WHERE account_id = ?", (account_id,)
        ).fetchone()
        return row["last_sort_at"] if row else None


def set_last_sort_at(account_id: str, iso_ts: str) -> None:
    with db_lock() as conn:
        conn.execute(
            """INSERT INTO sync_state (account_id, last_sort_at) VALUES (?, ?)
               ON CONFLICT(account_id) DO UPDATE SET last_sort_at=excluded.last_sort_at""",
            (account_id, iso_ts),
        )
        conn.commit()
