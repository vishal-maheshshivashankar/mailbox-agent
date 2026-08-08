"""One-off backfill: classify and label mail that predates this agent.

The regular sort loop (graphs/sort_loop.py) only ever fetches mail 'after:
last run' - or 'after: yesterday' on an account's very first run (see
toolkit/gmail.list_new_messages). Anything already in the mailbox before
that is invisible to it, and since the retention sweep only ever looks at
already-labeled mail, that backlog is invisible to retention too - forever,
unless it's been through here. Not part of the scheduler; run by hand,
once, per account.

    mailbox-agent-backfill --account personal
    mailbox-agent-backfill --account personal --before 2025/01/01
    mailbox-agent-backfill --account personal --dry-run
    mailbox-agent-backfill --account personal --limit 500

Safe to re-run: any message that already carries an AI/* label is skipped,
so an interrupted run (or a second pass with different --before/--after
bounds) never double-labels or re-spends an LLM call on the same message.

Heads up: once backfilled, this old mail is exactly what the *next*
scheduled retention sweep will see as candidates. Review the DRY_RUN
report (or the Telegram approval) before assuming nothing changed -
see README's retention section.
"""

import argparse
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone

from mailbox_agent.db import connection as db
from mailbox_agent.logging_config import configure_logging
from mailbox_agent.toolkit import gmail, llm, rules
from mailbox_agent.toolkit.models import Classification, EmailSummary

logger = logging.getLogger(__name__)

# Bounds memory and gives a progress checkpoint every round trip on a run
# that may cover thousands of messages.
BATCH_SIZE = 20


def run_for_account(
    account_id: str,
    before: str | None = None,
    after: str | None = None,
    limit: int = 5000,
    dry_run: bool = False,
) -> None:
    service = gmail.get_service(account_id)
    run_id = (
        f"{account_id}:backfill:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}:{uuid.uuid4().hex[:6]}"
    )

    ids = gmail.list_messages_in_range(service, after_date=after, before_date=before, max_results=limit)
    logger.info("account=%s scanning=%d candidate messages dry_run=%s", account_id, len(ids), dry_run)

    labeled = 0
    already_labeled = 0
    by_category: Counter[str] = Counter()
    labeled_ids: list[str] = []

    for i in range(0, len(ids), BATCH_SIZE):
        chunk_ids = ids[i : i + BATCH_SIZE]
        summaries: list[EmailSummary] = []
        for msg_id in chunk_ids:
            summary = gmail.get_message_summary(service, msg_id)
            if gmail.already_labeled_by_agent(service, account_id, summary.label_ids):
                already_labeled += 1
                continue
            summaries.append(summary)

        if not summaries:
            continue

        classifications: dict[str, Classification] = {}
        needs_llm = []
        for msg in summaries:
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

        for msg in summaries:
            classification = classifications.get(msg.id)
            if not classification:
                continue
            by_category[classification.category] += 1
            if dry_run:
                continue
            gmail.apply_category_label(service, account_id, msg.id, classification.category)
            labeled += 1
            labeled_ids.append(msg.id)
            if classification.confidence >= 0.85 and classification.reason != "learned sender rule":
                rules.learn(account_id, msg.sender, classification.category)

        logger.info(
            "account=%s progress=%d/%d labeled=%d already_labeled=%d",
            account_id,
            min(i + BATCH_SIZE, len(ids)),
            len(ids),
            labeled,
            already_labeled,
        )

    if not dry_run and labeled_ids:
        db.write_audit_log(
            account_id=account_id,
            run_id=run_id,
            action="backfill_label",
            message_ids=labeled_ids,
            detail={"labeled_count": labeled, "by_category": dict(by_category)},
        )

    logger.info(
        "account=%s backfill complete. labeled=%d already_labeled=%d by_category=%s dry_run=%s",
        account_id,
        labeled,
        already_labeled,
        dict(by_category),
        dry_run,
    )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--account", required=True, help="account id to backfill")
    parser.add_argument("--before", help="only mail before this date, YYYY/MM/DD (default: unbounded)")
    parser.add_argument("--after", help="only mail after this date, YYYY/MM/DD (default: unbounded)")
    parser.add_argument("--limit", type=int, default=5000, help="max messages to scan (default 5000)")
    parser.add_argument("--dry-run", action="store_true", help="classify and report only, apply no labels")
    args = parser.parse_args()

    run_for_account(
        args.account, before=args.before, after=args.after, limit=args.limit, dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
