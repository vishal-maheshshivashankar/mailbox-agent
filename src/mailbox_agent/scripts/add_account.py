"""Onboard a new Gmail account: runs the OAuth consent flow once and stores
the account. Usage:

    mailbox-agent-add-account --id personal --email you@gmail.com
"""

import argparse

from mailbox_agent.db import connection as db
from mailbox_agent.toolkit.gmail_auth import run_oauth_flow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="short account key, e.g. 'personal' or 'work'")
    parser.add_argument("--email", required=True, help="the Gmail address, for your own reference")
    args = parser.parse_args()

    print(f"Opening browser for OAuth consent - sign in as {args.email} and approve access...")
    run_oauth_flow(args.id)
    db.add_account(args.id, args.email)
    print(f"Account '{args.id}' ({args.email}) added.")


if __name__ == "__main__":
    main()
