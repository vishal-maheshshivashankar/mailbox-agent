"""Every unit test gets its own throwaway SQLite files and a fake-but-set
env, so tests never touch real credentials or a shared DB and can run in
any order. Scoped to tests/unit/ only - tests/eval/ deliberately does NOT
use this, since it needs a real GEMINI_API_KEY to call the actual model.
"""

import importlib

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite3"))
    monkeypatch.setenv("DRY_RUN", "false")

    from mailbox_agent import config

    importlib.reload(config)  # picks up the env vars set above

    from mailbox_agent.db import connection as db
    from mailbox_agent.scripts import graph_registry

    db.reset_connection()
    graph_registry.reset_graphs()

    yield

    db.reset_connection()
    graph_registry.reset_graphs()
