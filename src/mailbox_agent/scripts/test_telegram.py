"""End-to-end test of the Telegram integration, with Gmail/Drive entirely
mocked out - nothing in your real mailbox is ever touched by this, only the
Telegram send/long-poll/callback/resume path is real.

Plain connectivity check (confirms TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are
correct and the bot can actually message you):

    mailbox-agent-test-telegram

Full round-trip - sends a real message with real Approve/Reject buttons,
waits for you to tap one, resumes the graph exactly like a real retention
sweep would, and reuses the actual production callback handler
(scripts/telegram_bot._handle_callback) rather than reimplementing it:

    mailbox-agent-test-telegram --interactive
"""

import argparse
import logging
import time
import uuid
from unittest.mock import MagicMock, patch

from mailbox_agent.db import connection as db
from mailbox_agent.logging_config import configure_logging
from mailbox_agent.scripts.graph_registry import INVOKE_LOCK, get_sweep_graph
from mailbox_agent.toolkit import telegram
from mailbox_agent.toolkit.models import BackupManifest, EmailSummary

logger = logging.getLogger(__name__)

_TEST_ACCOUNT_ID = "telegram_test"


def check_connectivity() -> None:
    telegram.notify(
        "mailbox-agent connectivity test - if you can see this, "
        "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both correct."
    )
    print("Sent. Check Telegram now — you should see the message immediately.")


def _drain_stale_updates() -> int | None:
    """Discard any backlog sitting in Telegram's queue before we start
    listening, without processing it. Without this, every fresh invocation
    of this script (offset isn't persisted between runs, unlike the real
    poll_forever() loop) re-fetches old, already-handled callback queries
    from previous test runs and reprocesses them - against an
    already-resolved approval and a long-expired callback_query_id, which
    Telegram rejects. Found by running this test twice in a row."""
    offset = None
    while True:
        updates = telegram.get_updates(offset, timeout=0)
        if not updates:
            return offset
        offset = updates[-1]["update_id"] + 1


def run_interactive_round_trip(timeout_seconds: int) -> None:
    from mailbox_agent.scripts import telegram_bot

    print("Draining any stale backlog from previous test runs...")
    offset = _drain_stale_updates()

    db.add_account(_TEST_ACCOUNT_ID, "telegram-test@example.com")
    fake_candidates = [
        EmailSummary(
            id="t1", thread_id="t1", sender="test-sender@example.com", subject="Test candidate", snippet="s", date="d"
        )
    ]
    fake_manifest = BackupManifest(
        drive_file_id="test-fake-id", drive_file_link="https://example.com/fake-backup", message_count=1, message_ids=["t1"]
    )

    with (
        # Forced False regardless of your real .env DRY_RUN setting - this
        # test's whole point is to exercise the approval-button path, and
        # it's safe to force since Gmail/Drive are mocked below regardless.
        patch("mailbox_agent.graphs.retention_sweep.config.DRY_RUN", False),
        patch("mailbox_agent.graphs.retention_sweep._gmail_service", return_value=MagicMock()),
        patch("mailbox_agent.graphs.retention_sweep._drive_service", return_value=MagicMock()),
        patch("mailbox_agent.graphs.retention_sweep.gmail.find_retention_candidates", return_value=fake_candidates),
        patch("mailbox_agent.graphs.retention_sweep.drive.backup_messages_to_drive", return_value=fake_manifest),
        patch("mailbox_agent.graphs.retention_sweep.gmail.trash_message") as mock_trash,
    ):
        graph = get_sweep_graph()
        run_id = f"{_TEST_ACCOUNT_ID}:sweep:test:{uuid.uuid4().hex[:6]}"
        with INVOKE_LOCK:
            result = graph.invoke(
                {"account_id": _TEST_ACCOUNT_ID, "run_id": run_id}, config={"configurable": {"thread_id": run_id}}
            )
        this_approval_id = result.get("approval_id")

        print("Real Telegram message sent with Approve/Reject buttons - check Telegram now.")
        print(f"Waiting up to {timeout_seconds}s for your response (Ctrl+C to give up)...\n")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            updates = telegram.get_updates(offset, timeout=10)
            for update in updates:
                offset = update["update_id"] + 1
                cq = update.get("callback_query")
                # Only act on a tap for THIS run's approval - anything else
                # (a duplicate delivery, a race with another test run) is
                # consumed (offset advances) but not acted on.
                if cq and cq.get("data", "").endswith(f":{this_approval_id}"):
                    telegram_bot._handle_callback(update)  # the real production handler
                    print("\nGot your response, resumed the graph via the real callback handler.")
                    print(f"gmail.trash_message call count (mocked, so real Gmail untouched): {mock_trash.call_count}")
                    return
        print("\nTimed out waiting for a response - nothing resumed. Run again if you want to retry.")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--interactive", action="store_true", help="full round-trip: real buttons, waits for your tap"
    )
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for a button tap")
    args = parser.parse_args()

    if args.interactive:
        run_interactive_round_trip(args.timeout)
    else:
        check_connectivity()


if __name__ == "__main__":
    main()
