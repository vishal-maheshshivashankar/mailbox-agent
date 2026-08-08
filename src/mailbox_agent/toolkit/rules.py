"""Learned sender rules - the long-term "memory" that lets the agent improve
from your Telegram corrections instead of re-asking the LLM about the same
sender forever. Backed by the sender_rules table (see db/schema.sql).

This stands in for LangGraph's `Store` abstraction (see docs/ARCHITECTURE.md
section 4) - a plain SQLite table does the same job at this scale without
requiring Postgres.
"""

import re

from mailbox_agent.db import connection as db
from mailbox_agent.toolkit.models import Category


def _normalize_sender(sender: str) -> str:
    """'Some Name <foo@bar.com>' -> 'foo@bar.com'"""
    match = re.search(r"<([^>]+)>", sender)
    return (match.group(1) if match else sender).strip().lower()


def lookup(account_id: str, sender: str) -> Category | None:
    row = db.get_sender_rule(account_id, _normalize_sender(sender))
    return row["category"] if row else None


def learn(account_id: str, sender: str, category: Category, auto_delete: bool = False) -> None:
    db.upsert_sender_rule(account_id, _normalize_sender(sender), category, auto_delete)


def is_vip(account_id: str, sender: str) -> bool:
    return db.is_vip_sender(account_id, _normalize_sender(sender))


def add_vip(account_id: str, sender: str) -> None:
    db.add_vip_sender(account_id, _normalize_sender(sender))
