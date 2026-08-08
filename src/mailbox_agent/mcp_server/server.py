"""Optional MCP wrapper around the same toolkit the autonomous graphs use -
a manual override/inspection console usable from Claude Desktop or Claude
Code, without duplicating the Gmail/Drive/Telegram logic. See
docs/ARCHITECTURE.md section 8 for why this is a second front door, not the
primary path.

Run standalone: `python -m mailbox_agent.mcp_server.server`
Then point a local MCP client at it (stdio transport).
"""

import json

from mcp.server.fastmcp import FastMCP

from mailbox_agent import config
from mailbox_agent.db import connection as db
from mailbox_agent.scripts.graph_registry import get_sweep_graph
from mailbox_agent.toolkit import gmail, rules

mcp = FastMCP("mailbox-cleaner")


@mcp.tool()
def list_accounts() -> str:
    """List all onboarded Gmail accounts."""
    rows = db.list_accounts()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def preview_retention_candidates(account_id: str) -> str:
    """Preview (read-only) mail that the next retention sweep would flag for
    backup + deletion for this account - does not back up or delete anything."""
    service = gmail.get_service(account_id)
    candidates = gmail.find_retention_candidates(service, account_id, config.RETENTION_POLICY)
    candidates = [c for c in candidates if not rules.is_vip(account_id, c.sender)]
    return json.dumps(
        {
            "count": len(candidates),
            "senders": sorted({c.sender for c in candidates})[:20],
            "sample_subjects": [c.subject for c in candidates[:10]],
        }
    )


@mcp.tool()
def list_pending_approvals() -> str:
    """List retention-sweep deletions currently awaiting Telegram approval."""
    with db.db_lock() as conn:
        rows = conn.execute(
            "SELECT id, account_id, status, created_at FROM pending_approvals WHERE status = 'pending'"
        ).fetchall()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def resolve_approval_manually(approval_id: str, decision: str) -> str:
    """Manually approve or reject a pending deletion from here instead of
    Telegram. decision must be 'approved' or 'rejected'."""
    if decision not in ("approved", "rejected"):
        return "error: decision must be 'approved' or 'rejected'"
    row = db.resolve_pending_approval(approval_id, decision)
    if row is None:
        return f"error: no pending approval with id {approval_id}"

    from langgraph.types import Command

    graph = get_sweep_graph()
    result = graph.invoke(Command(resume=decision), config={"configurable": {"thread_id": row["thread_id"]}})
    return json.dumps({"decision": decision, "trashed_count": result.get("trashed_count", 0)})


@mcp.tool()
def add_vip_sender(account_id: str, sender_email: str) -> str:
    """Mark a sender as VIP for this account - their mail is never
    auto-classified for deletion, regardless of label or age."""
    rules.add_vip(account_id, sender_email)
    return f"{sender_email} marked VIP for account {account_id}"


if __name__ == "__main__":
    mcp.run()
