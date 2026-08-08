"""Graph A - Sort Loop: fetch -> classify -> apply learned rules -> label -> audit.

Runs frequently and unattended. Never deletes or archives anything, which is
what makes that safe. See docs/ARCHITECTURE.md section 5.
"""

import logging
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from mailbox_agent.db import connection as db
from mailbox_agent.graphs.state import SortState
from mailbox_agent.toolkit import gmail, llm, rules
from mailbox_agent.toolkit.models import Classification, EmailSummary

logger = logging.getLogger(__name__)

_service_cache: dict[str, object] = {}


def _gmail_service(account_id: str):
    if account_id not in _service_cache:
        _service_cache[account_id] = gmail.get_service(account_id)
    return _service_cache[account_id]


def fetch_new_messages(state: SortState) -> dict:
    account_id = state["account_id"]
    service = _gmail_service(account_id)

    last_sort_at = db.get_last_sort_at(account_id)
    since_date = None
    if last_sort_at:
        since_date = datetime.fromisoformat(last_sort_at).strftime("%Y/%m/%d")

    ids = gmail.list_new_messages(service, since_date=since_date)
    messages = []
    for msg_id in ids:
        summary = gmail.get_message_summary(service, msg_id)
        if not gmail.already_labeled_by_agent(service, account_id, summary.label_ids):
            messages.append(summary.model_dump())

    logger.info("account=%s fetched=%d new=%d", account_id, len(ids), len(messages))
    return {"messages": messages}


def classify_messages(state: SortState) -> dict:
    account_id = state["account_id"]
    messages = [EmailSummary(**m) for m in state.get("messages", [])]

    classifications: dict[str, Classification] = {}
    needs_llm = []
    for msg in messages:
        learned = rules.lookup(account_id, msg.sender)
        if learned:
            classifications[msg.id] = Classification(
                message_id=msg.id, category=learned, confidence=1.0, reason="learned sender rule"
            )
        else:
            needs_llm.append(msg)

    if needs_llm:
        for c in llm.classify_batch(needs_llm):
            classifications[c.message_id] = c

    return {"classifications": {mid: c.model_dump() for mid, c in classifications.items()}}


def apply_labels(state: SortState) -> dict:
    account_id = state["account_id"]
    service = _gmail_service(account_id)
    messages = [EmailSummary(**m) for m in state.get("messages", [])]
    classifications = {mid: Classification(**c) for mid, c in state.get("classifications", {}).items()}

    labeled = 0
    for msg in messages:
        classification = classifications.get(msg.id)
        if not classification:
            continue
        gmail.apply_category_label(service, account_id, msg.id, classification.category)
        labeled += 1
        # High-confidence LLM calls teach the sender rule so repeat senders
        # skip the model entirely next time (see toolkit/rules.py).
        if classification.confidence >= 0.85 and classification.reason != "learned sender rule":
            rules.learn(account_id, msg.sender, classification.category)

    return {"labeled_count": labeled}


def write_audit(state: SortState) -> dict:
    account_id = state["account_id"]
    classifications = state.get("classifications", {})
    db.write_audit_log(
        account_id=account_id,
        run_id=state["run_id"],
        action="label",
        message_ids=list(classifications.keys()),
        detail={"labeled_count": state.get("labeled_count", 0)},
    )
    db.set_last_sort_at(account_id, datetime.now(timezone.utc).isoformat())
    return {}


def build_sort_graph():
    builder = StateGraph(SortState)
    builder.add_node("fetch_new_messages", fetch_new_messages)
    builder.add_node("classify_messages", classify_messages)
    builder.add_node("apply_labels", apply_labels)
    builder.add_node("write_audit", write_audit)

    builder.add_edge(START, "fetch_new_messages")
    builder.add_edge("fetch_new_messages", "classify_messages")
    builder.add_edge("classify_messages", "apply_labels")
    builder.add_edge("apply_labels", "write_audit")
    builder.add_edge("write_audit", END)
    return builder
