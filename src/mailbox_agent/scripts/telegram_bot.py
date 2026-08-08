"""Long-polls Telegram for Approve/Reject taps and resumes the paused
retention-sweep graph thread accordingly. Also expires stale approvals after
APPROVAL_TTL_HOURS so a missed notification can't leave a graph paused
forever (see docs/ARCHITECTURE.md section 6).

    mailbox-agent-telegram-bot
"""

import logging
import time

from langgraph.types import Command

from mailbox_agent import config
from mailbox_agent.db import connection as db
from mailbox_agent.logging_config import configure_logging
from mailbox_agent.scripts.graph_registry import INVOKE_LOCK, get_sweep_graph
from mailbox_agent.toolkit import telegram

logger = logging.getLogger(__name__)


def _resume_thread(thread_id: str, decision: str) -> dict:
    graph = get_sweep_graph()
    config_ = {"configurable": {"thread_id": thread_id}}
    with INVOKE_LOCK:
        return graph.invoke(Command(resume=decision), config=config_)


def _handle_callback(update: dict) -> None:
    cq = update["callback_query"]
    data = cq.get("data", "")
    if ":" not in data:
        return
    action, approval_id = data.split(":", 1)
    decision = "approved" if action == "approve" else "rejected"

    row = db.resolve_pending_approval(approval_id, decision)
    if row is None:
        telegram.answer_callback_query(cq["id"], "Unknown or already-handled request.")
        return

    result = _resume_thread(row["thread_id"], decision)
    trashed = result.get("trashed_count", 0)

    if decision == "approved":
        confirm = f"✅ Approved — {trashed} emails moved to Trash."
    else:
        confirm = "❌ Rejected — nothing deleted, backup stays in Drive."

    telegram.answer_callback_query(cq["id"], confirm)
    message = cq.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    if chat_id is not None and message_id is not None:
        telegram.edit_message_text(chat_id, message_id, confirm)

    logger.info(
        "approval resolved",
        extra={
            "approval_id": approval_id,
            "account_id": row["account_id"],
            "decision": decision,
            "trashed_count": trashed,
        },
    )


def check_expired_approvals() -> None:
    for row in db.get_expired_pending_approvals(config.APPROVAL_TTL_HOURS):
        logger.info(
            "approval expired, re-queuing for next sweep",
            extra={"approval_id": row["id"], "ttl_hours": config.APPROVAL_TTL_HOURS},
        )
        db.resolve_pending_approval(row["id"], "expired")
        try:
            _resume_thread(row["thread_id"], "expired")
        except Exception:
            logger.exception("failed to resume expired thread", extra={"thread_id": row["thread_id"]})


def poll_forever() -> None:
    logger.info("Telegram approval listener started (long polling, no inbound port needed)")
    offset = None
    while True:
        try:
            check_expired_approvals()
            updates = telegram.get_updates(offset, timeout=30)
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    _handle_callback(update)
        except Exception:
            logger.exception("telegram poll loop error, retrying in 5s")
            time.sleep(5)


def main() -> None:
    configure_logging()
    poll_forever()


if __name__ == "__main__":
    main()
