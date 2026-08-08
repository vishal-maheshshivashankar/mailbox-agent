"""Graph A entrypoint: fetch, classify, label. Safe to run unattended.

mailbox-agent-sort              # all accounts
mailbox-agent-sort --account personal
"""

import argparse
import logging
import uuid
from datetime import datetime, timezone

from mailbox_agent.db import connection as db
from mailbox_agent.logging_config import configure_logging
from mailbox_agent.scripts.graph_registry import INVOKE_LOCK, get_sort_graph

logger = logging.getLogger(__name__)


def run_for_account(account_id: str) -> None:
    graph = get_sort_graph()
    run_id = (
        f"{account_id}:sort:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}:{uuid.uuid4().hex[:6]}"
    )
    initial_state = {"account_id": account_id, "run_id": run_id}
    config_ = {"configurable": {"thread_id": run_id}}
    with INVOKE_LOCK:
        result = graph.invoke(initial_state, config=config_)
    logger.info(
        "sort loop completed",
        extra={"account_id": account_id, "labeled_count": result.get("labeled_count", 0)},
    )


def run_for_all_accounts() -> None:
    for row in db.list_accounts():
        try:
            run_for_account(row["id"])
        except Exception:
            logger.exception("sort loop failed", extra={"account_id": row["id"]})


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", help="run for a single account id; default is all accounts")
    args = parser.parse_args()

    if args.account:
        run_for_account(args.account)
    else:
        run_for_all_accounts()


if __name__ == "__main__":
    main()
