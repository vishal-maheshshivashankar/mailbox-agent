"""Graph B - Retention Sweep: find old low-value mail -> back up to Drive ->
pause for Telegram approval -> trash (never permanent delete) only if
approved. See docs/ARCHITECTURE.md section 6.

Important LangGraph subtlety: on resume, a node's code re-runs from its top,
with `interrupt()` calls resolved from resume values in call order instead
of pausing again. Any side effect that must happen exactly once (sending the
Telegram message, writing the pending_approvals row) therefore lives in its
own node, separate from the node that calls interrupt() - see
create_approval_request vs. wait_for_approval below.
"""

import logging
import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from mailbox_agent import config
from mailbox_agent.db import connection as db
from mailbox_agent.graphs.state import SweepState
from mailbox_agent.toolkit import drive, gmail, rules, telegram
from mailbox_agent.toolkit.gmail import CATEGORY_LABELS
from mailbox_agent.toolkit.models import BackupManifest, EmailSummary

logger = logging.getLogger(__name__)

_gmail_cache: dict[str, object] = {}
_drive_cache: dict[str, object] = {}


def _gmail_service(account_id: str):
    if account_id not in _gmail_cache:
        _gmail_cache[account_id] = gmail.get_service(account_id)
    return _gmail_cache[account_id]


def _drive_service(account_id: str):
    if account_id not in _drive_cache:
        _drive_cache[account_id] = drive.get_service(account_id)
    return _drive_cache[account_id]


def _policy_summary() -> str:
    # Plain str keys, not Category-keyed - config.RETENTION_POLICY entries
    # are unvalidated user config and may not even be real categories.
    labels_by_key: dict[str, str] = {str(k): v for k, v in CATEGORY_LABELS.items()}
    parts = []
    for category, days in config.RETENTION_POLICY.items():
        label = labels_by_key.get(category, category)
        window = "next sweep" if days == 0 else f"{days}d"
        parts.append(f"{label} ({window})")
    return ", ".join(parts)


def find_candidates(state: SweepState) -> dict:
    account_id = state["account_id"]
    service = _gmail_service(account_id)
    raw = gmail.find_retention_candidates(service, account_id, config.RETENTION_POLICY)
    candidates = [c for c in raw if not rules.is_vip(account_id, c.sender)]
    logger.info("account=%s retention_candidates=%d (vip-excluded)", account_id, len(candidates))
    return {"candidates": [c.model_dump() for c in candidates]}


def route_after_find(state: SweepState) -> str:
    if not state.get("candidates"):
        return "no_candidates"
    if config.DRY_RUN:
        return "dry_run"
    return "proceed"


def dry_run_report(state: SweepState) -> dict:
    account_id = state["account_id"]
    candidates = [EmailSummary(**c) for c in state["candidates"]]
    senders = sorted({c.sender for c in candidates})[:10]
    text = (
        f"[DRY RUN] Retention sweep — {account_id}\n"
        f"{len(candidates)} emails matched the retention policy ({_policy_summary()}) and would be "
        f"backed up and offered for deletion.\nTop senders: {', '.join(senders)}\n\n"
        f"Set DRY_RUN=false in .env to enable real backup + approval + delete."
    )
    telegram.notify(text)
    db.write_audit_log(
        account_id=account_id,
        run_id=state["run_id"],
        action="dry_run_report",
        message_ids=[c.id for c in candidates],
        detail={"count": len(candidates)},
    )
    return {}


def backup_to_drive(state: SweepState) -> dict:
    account_id = state["account_id"]
    gmail_service = _gmail_service(account_id)
    drive_service = _drive_service(account_id)
    candidates = [EmailSummary(**c) for c in state["candidates"]]
    manifest = drive.backup_messages_to_drive(
        gmail_service, drive_service, account_id, candidates, gmail.get_raw_message
    )
    logger.info(
        "account=%s backed_up=%d drive_file=%s", account_id, manifest.message_count, manifest.drive_file_id
    )
    return {"backup_manifest": manifest.model_dump()}


def create_approval_request(state: SweepState) -> dict:
    account_id = state["account_id"]
    candidates = [EmailSummary(**c) for c in state["candidates"]]
    manifest_dict = state["backup_manifest"]
    assert manifest_dict is not None, "create_approval_request always runs after backup_to_drive"
    manifest = BackupManifest(**manifest_dict)
    approval_id = str(uuid.uuid4())

    senders = sorted({c.sender for c in candidates})[:10]
    text = (
        f"Retention sweep — {account_id}\n"
        f"{len(candidates)} emails matched the retention policy ({_policy_summary()}).\n"
        f"Backed up to Drive: {manifest.drive_file_link}\n"
        f"Top senders: {', '.join(senders)}\n\n"
        f"Move these to Trash? (Gmail keeps a 30-day recovery window either way)"
    )
    db.create_pending_approval(
        approval_id, account_id, state["run_id"], {"text": text, "count": len(candidates)}
    )
    telegram.send_approval_request(text, approval_id)
    logger.info("account=%s approval_requested=%s", account_id, approval_id)
    return {"approval_id": approval_id}


def wait_for_approval(state: SweepState) -> dict:
    decision = interrupt({"approval_id": state["approval_id"], "account_id": state["account_id"]})
    return {"approval_status": decision}


def route_after_approval(state: SweepState) -> str:
    return state.get("approval_status") or "rejected"


def trash_messages(state: SweepState) -> dict:
    account_id = state["account_id"]
    service = _gmail_service(account_id)
    manifest_dict = state["backup_manifest"]
    assert manifest_dict is not None, "trash_messages only runs after an approved backup"
    manifest = BackupManifest(**manifest_dict)
    for msg_id in manifest.message_ids:
        gmail.trash_message(service, msg_id)
    logger.info("account=%s trashed=%d", account_id, len(manifest.message_ids))
    return {"trashed_count": len(manifest.message_ids)}


def mark_skipped(state: SweepState) -> dict:
    return {}


def write_audit(state: SweepState) -> dict:
    account_id = state["account_id"]
    manifest_dict = state.get("backup_manifest")
    manifest = BackupManifest(**manifest_dict) if manifest_dict else None
    status = state.get("approval_status") or "rejected"
    action = {"approved": "trash", "rejected": "skip", "expired": "skip"}.get(status, "skip")
    db.write_audit_log(
        account_id=account_id,
        run_id=state["run_id"],
        action=action,
        message_ids=manifest.message_ids if manifest else [],
        detail={
            "approval_status": state.get("approval_status"),
            "trashed_count": state.get("trashed_count", 0),
            "drive_file_id": manifest.drive_file_id if manifest else None,
        },
    )
    return {}


def build_sweep_graph():
    builder = StateGraph(SweepState)
    builder.add_node("find_candidates", find_candidates)
    builder.add_node("dry_run_report", dry_run_report)
    builder.add_node("backup_to_drive", backup_to_drive)
    builder.add_node("create_approval_request", create_approval_request)
    builder.add_node("wait_for_approval", wait_for_approval)
    builder.add_node("trash_messages", trash_messages)
    builder.add_node("mark_skipped", mark_skipped)
    builder.add_node("write_audit", write_audit)

    builder.add_edge(START, "find_candidates")
    builder.add_conditional_edges(
        "find_candidates",
        route_after_find,
        {"no_candidates": END, "dry_run": "dry_run_report", "proceed": "backup_to_drive"},
    )
    builder.add_edge("dry_run_report", END)
    builder.add_edge("backup_to_drive", "create_approval_request")
    builder.add_edge("create_approval_request", "wait_for_approval")
    builder.add_conditional_edges(
        "wait_for_approval",
        route_after_approval,
        {"approved": "trash_messages", "rejected": "mark_skipped", "expired": "mark_skipped"},
    )
    builder.add_edge("trash_messages", "write_audit")
    builder.add_edge("mark_skipped", "write_audit")
    builder.add_edge("write_audit", END)
    return builder
