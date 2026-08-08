"""Graph A end-to-end with Gmail/Gemini mocked out - verifies the actual
wiring (fetch -> classify -> label -> audit) and the learned-sender-rule
shortcut, not just that each function works in isolation.
"""

from unittest.mock import MagicMock, patch

from mailbox_agent.db import connection as db
from mailbox_agent.toolkit.models import Classification, EmailSummary


def test_sort_loop_labels_and_learns_sender_rule():
    db.add_account("acct1", "a@example.com")
    msg1 = EmailSummary(
        id="m1", thread_id="t1", sender="promo@shop.com", subject="Big sale", snippet="save now", date="d"
    )
    classification = Classification(
        message_id="m1", category="promotions", confidence=0.95, reason="marketing language"
    )

    with (
        patch("mailbox_agent.graphs.sort_loop._gmail_service", return_value=MagicMock()),
        patch("mailbox_agent.graphs.sort_loop.gmail.list_new_messages", return_value=["m1"]),
        patch("mailbox_agent.graphs.sort_loop.gmail.get_message_summary", return_value=msg1),
        patch("mailbox_agent.graphs.sort_loop.gmail.already_labeled_by_agent", return_value=False),
        patch("mailbox_agent.graphs.sort_loop.llm.classify_batch", return_value=[classification]) as mock_llm,
        patch(
            "mailbox_agent.graphs.sort_loop.gmail.apply_category_label", return_value="AI/Promotions"
        ) as mock_label,
    ):
        from mailbox_agent.scripts.run_sort import run_for_account

        run_for_account("acct1")

        assert mock_llm.call_count == 1
        assert mock_label.call_count == 1

        # Second message from the SAME sender: the learned rule from the
        # first run should short-circuit the LLM call entirely.
        msg2 = EmailSummary(
            id="m2", thread_id="t2", sender="promo@shop.com", subject="Another sale", snippet="x", date="d"
        )
        with (
            patch("mailbox_agent.graphs.sort_loop.gmail.list_new_messages", return_value=["m2"]),
            patch("mailbox_agent.graphs.sort_loop.gmail.get_message_summary", return_value=msg2),
        ):
            run_for_account("acct1")

        assert mock_llm.call_count == 1, "LLM should not be called again for a known sender"
        assert mock_label.call_count == 2

    with db.db_lock() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert actions == ["label", "label"]
