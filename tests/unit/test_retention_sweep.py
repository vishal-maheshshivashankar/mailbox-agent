"""Graph B end-to-end with Gmail/Drive/Telegram mocked out.

The important thing this guards against: LangGraph re-runs a node's code
from the top on resume, so a naive implementation could double-send the
Telegram message or double-write the pending_approvals row when the human
taps Approve. create_approval_request (side effects) is a separate node
from wait_for_approval (the interrupt() call) specifically to prevent that -
this test fails loudly if that separation ever regresses.
"""

from unittest.mock import MagicMock, patch

from langgraph.types import Command

from mailbox_agent.db import connection as db
from mailbox_agent.scripts.graph_registry import INVOKE_LOCK, get_sweep_graph
from mailbox_agent.toolkit.models import BackupManifest, EmailSummary


def _fake_candidates():
    return [
        EmailSummary(
            id="m1", thread_id="t1", sender="deals@shop.com", subject="50% off", snippet="sale", date="d"
        ),
        EmailSummary(
            id="m2", thread_id="t2", sender="deals@shop.com", subject="Flash sale", snippet="sale2", date="d"
        ),
    ]


def test_retention_sweep_pauses_then_resumes_without_double_side_effects():
    db.add_account("testacct", "test@example.com")
    fake_manifest = BackupManifest(
        drive_file_id="fake123",
        drive_file_link="https://drive/fake123",
        message_count=2,
        message_ids=["m1", "m2"],
    )

    with (
        patch("mailbox_agent.graphs.retention_sweep._gmail_service", return_value=MagicMock()),
        patch("mailbox_agent.graphs.retention_sweep._drive_service", return_value=MagicMock()),
        patch(
            "mailbox_agent.graphs.retention_sweep.gmail.find_retention_candidates",
            return_value=_fake_candidates(),
        ) as mock_find,
        patch(
            "mailbox_agent.graphs.retention_sweep.drive.backup_messages_to_drive", return_value=fake_manifest
        ) as mock_backup,
        patch(
            "mailbox_agent.graphs.retention_sweep.telegram.send_approval_request",
            return_value={"message_id": 1},
        ) as mock_send,
        patch("mailbox_agent.graphs.retention_sweep.gmail.trash_message") as mock_trash,
    ):
        from mailbox_agent.scripts.run_sweep import run_for_account

        run_for_account("testacct")

        assert mock_find.call_count == 1
        assert mock_backup.call_count == 1
        assert mock_send.call_count == 1

        with db.db_lock() as conn:
            row = conn.execute("SELECT * FROM pending_approvals").fetchone()
        assert row is not None
        assert row["status"] == "pending"

        db.resolve_pending_approval(row["id"], "approved")
        graph = get_sweep_graph()
        with INVOKE_LOCK:
            result = graph.invoke(
                Command(resume="approved"), config={"configurable": {"thread_id": row["thread_id"]}}
            )

        assert mock_send.call_count == 1, "telegram message must not be re-sent on resume"
        assert mock_trash.call_count == 2
        assert result["trashed_count"] == 2

    with db.db_lock() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "trash" in actions


def test_rejected_approval_does_not_trash_anything():
    db.add_account("testacct2", "test2@example.com")
    fake_manifest = BackupManifest(
        drive_file_id="fake456", drive_file_link="https://drive/fake456", message_count=1, message_ids=["m3"]
    )

    with (
        patch("mailbox_agent.graphs.retention_sweep._gmail_service", return_value=MagicMock()),
        patch("mailbox_agent.graphs.retention_sweep._drive_service", return_value=MagicMock()),
        patch(
            "mailbox_agent.graphs.retention_sweep.gmail.find_retention_candidates",
            return_value=[
                EmailSummary(id="m3", thread_id="t3", sender="x@y.com", subject="s", snippet="s", date="d")
            ],
        ),
        patch(
            "mailbox_agent.graphs.retention_sweep.drive.backup_messages_to_drive", return_value=fake_manifest
        ),
        patch("mailbox_agent.graphs.retention_sweep.telegram.send_approval_request", return_value={}),
        patch("mailbox_agent.graphs.retention_sweep.gmail.trash_message") as mock_trash,
    ):
        from mailbox_agent.scripts.run_sweep import run_for_account

        run_for_account("testacct2")

        with db.db_lock() as conn:
            row = conn.execute("SELECT * FROM pending_approvals WHERE account_id = 'testacct2'").fetchone()

        db.resolve_pending_approval(row["id"], "rejected")
        graph = get_sweep_graph()
        with INVOKE_LOCK:
            result = graph.invoke(
                Command(resume="rejected"), config={"configurable": {"thread_id": row["thread_id"]}}
            )

        assert mock_trash.call_count == 0
        assert result.get("trashed_count", 0) == 0
