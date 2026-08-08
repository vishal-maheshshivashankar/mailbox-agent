"""Read-only: fetches messages matching a Gmail search query and shows what
the classifier would label them - never applies a label, never touches
Gmail beyond a search + metadata read. Built for exactly this situation:
testing a new/changed category against real mail before trusting the sort
loop to act on it for real, and for checking already-labeled mail (which
the sort loop skips) without needing a relabel/backfill tool.

    mailbox-agent-preview-classify --account personal \\
        --query "statement OR EMI OR mandate OR autopay OR autodebit OR premium"
"""

import argparse

from mailbox_agent.toolkit import gmail, llm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument(
        "--query",
        default="",
        help="Gmail search query to narrow candidates, e.g. 'statement OR EMI OR mandate'. "
        "Empty means 'recent mail, no filter'.",
    )
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()

    service = gmail.get_service(args.account)
    query = f"-in:chat -in:trash -in:spam {args.query}".strip()
    resp = service.users().messages().list(userId="me", q=query, maxResults=args.limit).execute()
    ids = [m["id"] for m in resp.get("messages", [])]

    if not ids:
        print(f"No messages matched query: {query!r}")
        return

    messages = [gmail.get_message_summary(service, mid) for mid in ids]
    classifications = llm.classify_batch(messages)
    by_id = {c.message_id: c for c in classifications}

    print(f"{len(messages)} messages matched {query!r}\n")
    print(f"{'category':<14}{'conf':<7}{'sender':<42}subject")
    print("-" * 110)
    for msg in messages:
        c = by_id.get(msg.id)
        category = c.category if c else "?"
        confidence = f"{c.confidence:.2f}" if c else "?"
        print(f"{category:<14}{confidence:<7}{msg.sender[:40]:<42}{msg.subject[:60]}")


if __name__ == "__main__":
    main()
