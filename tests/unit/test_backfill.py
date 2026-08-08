"""Backfill script with Gmail/Gemini mocked out - verifies it labels
unlabeled backlog mail, skips anything already carrying an AI/* label, and
that --dry-run classifies without labeling or learning rules.
"""

from unittest.mock import MagicMock, patch

from mailbox_agent.db import connection as db
from mailbox_agent.toolkit.models import Classification, EmailSummary


def test_backfill_labels_unlabeled_and_skips_already_labeled():
    db.add_account("acct1", "a@example.com")
    old_msg = EmailSummary(
        id="m1", thread_id="t1", sender="promo@shop.com", subject="Old sale", snippet="save now", date="d"
    )
    classification = Classification(
        message_id="m1", category="promotions", confidence=0.95, reason="marketing language"
    )

    with (
        patch("mailbox_agent.scripts.backfill_classify.gmail.get_service", return_value=MagicMock()),
        patch(
            "mailbox_agent.scripts.backfill_classify.gmail.list_messages_in_range",
            return_value=["m1", "m2"],
        ),
        patch(
            "mailbox_agent.scripts.backfill_classify.gmail.get_message_summary",
            side_effect=lambda service, msg_id: old_msg
            if msg_id == "m1"
            else old_msg.model_copy(update={"id": "m2", "label_ids": ["existing-ai-label"]}),
        ),
        patch(
            "mailbox_agent.scripts.backfill_classify.gmail.already_labeled_by_agent",
            side_effect=lambda service, account_id, label_ids: "existing-ai-label" in label_ids,
        ),
        patch(
            "mailbox_agent.scripts.backfill_classify.llm.classify_batch", return_value=[classification]
        ) as mock_llm,
        patch(
            "mailbox_agent.scripts.backfill_classify.gmail.apply_category_label", return_value="AI/Promotions"
        ) as mock_label,
    ):
        from mailbox_agent.scripts.backfill_classify import run_for_account

        run_for_account("acct1")

        # m2 already carries an AI label, so only m1 goes through classify+label.
        assert mock_llm.call_count == 1
        assert mock_label.call_count == 1
        mock_label.assert_called_once_with(mock_label.call_args.args[0], "acct1", "m1", "promotions")

    with db.db_lock() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert actions == ["backfill_label"]


def test_backfill_dry_run_does_not_label_or_write_audit():
    db.add_account("acct1", "a@example.com")
    msg = EmailSummary(id="m1", thread_id="t1", sender="promo@shop.com", subject="s", snippet="x", date="d")
    classification = Classification(message_id="m1", category="promotions", confidence=0.95, reason="r")

    with (
        patch("mailbox_agent.scripts.backfill_classify.gmail.get_service", return_value=MagicMock()),
        patch("mailbox_agent.scripts.backfill_classify.gmail.list_messages_in_range", return_value=["m1"]),
        patch("mailbox_agent.scripts.backfill_classify.gmail.get_message_summary", return_value=msg),
        patch("mailbox_agent.scripts.backfill_classify.gmail.already_labeled_by_agent", return_value=False),
        patch("mailbox_agent.scripts.backfill_classify.llm.classify_batch", return_value=[classification]),
        patch("mailbox_agent.scripts.backfill_classify.gmail.apply_category_label") as mock_label,
    ):
        from mailbox_agent.scripts.backfill_classify import run_for_account

        run_for_account("acct1", dry_run=True)

        mock_label.assert_not_called()

    with db.db_lock() as conn:
        rows = conn.execute("SELECT action FROM audit_log").fetchall()
    assert rows == []
