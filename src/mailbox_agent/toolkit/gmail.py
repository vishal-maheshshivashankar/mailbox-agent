"""Gmail operations. Plain google-api-python-client calls - no MCP hop here,
see docs/ARCHITECTURE.md section 8 for why the automated pipeline calls the API
directly while an MCP wrapper (mcp_server/server.py) exposes the same
functions for manual/interactive use.

Retries: every single `.execute()` call is isolated into its own small
function so retry_read/retry_idempotent_write (toolkit/retry.py) retry just
that one HTTP call, not an entire pagination loop. See retry.py's docstring
for which operations are safe to retry and why.
"""

import base64
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mailbox_agent.toolkit.gmail_auth import load_credentials
from mailbox_agent.toolkit.models import Category, EmailSummary
from mailbox_agent.toolkit.retry import retry_idempotent_write, retry_read

CATEGORY_LABELS: dict[Category, str] = {
    "important": "AI/Important",
    "promotions": "AI/Promotions",
    "social": "AI/Social",
    "newsletters": "AI/Newsletters",
    "receipts": "AI/Receipts",
    "statements": "AI/Statements",
    "e_mandate": "AI/E-Mandate",
    "personal": "AI/Personal",
    "other": "AI/Other",
}

_label_cache: dict[tuple[str, str], str] = {}


def get_service(account_id: str):
    creds = load_credentials(account_id)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


@retry_read
def _list_labels(service) -> dict:
    return service.users().labels().list(userId="me").execute()


@retry_idempotent_write
def _create_label(service, label_name: str) -> dict:
    try:
        return (
            service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 409:
            # A retried attempt can land here after an earlier try actually
            # succeeded server-side but the response was lost - look the
            # label up instead of failing the run over a false negative.
            for label in _list_labels(service).get("labels", []):
                if label["name"] == label_name:
                    return label
        raise


def ensure_label(service, account_id: str, label_name: str) -> str:
    cache_key = (account_id, label_name)
    if cache_key in _label_cache:
        return _label_cache[cache_key]

    for label in _list_labels(service).get("labels", []):
        if label["name"] == label_name:
            _label_cache[cache_key] = label["id"]
            return label["id"]

    created = _create_label(service, label_name)
    _label_cache[cache_key] = created["id"]
    return created["id"]


@retry_read
def _list_messages_page(service, query: str, page_token: str | None, max_results: int) -> dict:
    return (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results, pageToken=page_token)
        .execute()
    )


def list_new_messages(service, since_date: str | None, max_results: int = 200) -> list[str]:
    """Returns message ids. `since_date` is 'YYYY/MM/DD' (Gmail search granularity is daily)."""
    query = "-in:chat -in:trash -in:spam"
    if since_date:
        query += f" after:{since_date}"
    else:
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y/%m/%d")
        query += f" after:{yesterday}"

    ids: list[str] = []
    page_token = None
    while True:
        resp = _list_messages_page(service, query, page_token, min(100, max_results - len(ids)))
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= max_results:
            break
    return ids


def list_messages_in_range(
    service, after_date: str | None = None, before_date: str | None = None, max_results: int = 5000
) -> list[str]:
    """Like `list_new_messages` but with no implicit 'yesterday' fallback -
    `after_date`/`before_date` are 'YYYY/MM/DD' or None for unbounded on
    that side. Used by the one-off backfill script (scripts/backfill_classify.py)
    to reach mail older than an account's first sort-loop run, which
    `list_new_messages` structurally can't see."""
    query = "-in:chat -in:trash -in:spam"
    if after_date:
        query += f" after:{after_date}"
    if before_date:
        query += f" before:{before_date}"

    ids: list[str] = []
    page_token = None
    while True:
        resp = _list_messages_page(service, query, page_token, min(100, max_results - len(ids)))
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= max_results:
            break
    return ids


@retry_read
def get_message_summary(service, msg_id: str) -> EmailSummary:
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
        .execute()
    )
    headers = msg["payload"].get("headers", [])
    return EmailSummary(
        id=msg["id"],
        thread_id=msg["threadId"],
        sender=_header(headers, "From"),
        subject=_header(headers, "Subject"),
        snippet=msg.get("snippet", ""),
        date=_header(headers, "Date"),
        label_ids=msg.get("labelIds", []),
    )


def already_labeled_by_agent(service, account_id: str, label_ids: list[str]) -> bool:
    agent_label_ids = {ensure_label(service, account_id, name) for name in CATEGORY_LABELS.values()}
    return bool(agent_label_ids.intersection(label_ids))


@retry_idempotent_write
def _modify_message(service, msg_id: str, add_label_ids: list[str]) -> None:
    # Adding a label a message already has is a no-op on Gmail's side, so
    # this is safe to retry blindly.
    service.users().messages().modify(userId="me", id=msg_id, body={"addLabelIds": add_label_ids}).execute()


def apply_category_label(service, account_id: str, msg_id: str, category: Category) -> str:
    label_name = CATEGORY_LABELS[category]
    label_id = ensure_label(service, account_id, label_name)
    _modify_message(service, msg_id, [label_id])
    return label_name


def find_retention_candidates(
    service,
    account_id: str,
    retention_policy: dict[str, int],
    max_results: int = 500,
) -> list[EmailSummary]:
    """`retention_policy` maps category -> days old before it's a candidate
    (e.g. {"promotions": 0, "newsletters": 365}). A category absent from the
    policy is never queried here - see config.RETENTION_POLICY.

    Starred and Gmail-important-flagged mail is excluded regardless of
    category or age - that filter is deliberately unconditional, not
    something a per-category policy can override.
    """
    seen: dict[str, EmailSummary] = {}
    for category, retention_days in retention_policy.items():
        if category not in CATEGORY_LABELS:
            continue
        label_name = CATEGORY_LABELS[category]
        before_date = (datetime.utcnow() - timedelta(days=retention_days)).strftime("%Y/%m/%d")
        query = f'label:"{label_name}" before:{before_date} -is:starred -is:important'
        page_token = None
        while True:
            resp = _list_messages_page(service, query, page_token, 100)
            for m in resp.get("messages", []):
                if m["id"] not in seen and len(seen) < max_results:
                    seen[m["id"]] = get_message_summary(service, m["id"])
            page_token = resp.get("nextPageToken")
            if not page_token or len(seen) >= max_results:
                break
    return list(seen.values())


@retry_read
def get_raw_message(service, msg_id: str) -> bytes:
    """Full RFC822 source, for Drive backup as .eml."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="raw").execute()
    return base64.urlsafe_b64decode(msg["raw"])


@retry_idempotent_write
def trash_message(service, msg_id: str) -> None:
    """Moves to Gmail Trash (auto-purges in 30 days) - never permanent delete.
    Trashing an already-trashed message is a no-op, so safe to retry.
    See docs/ARCHITECTURE.md safety defaults."""
    service.users().messages().trash(userId="me", id=msg_id).execute()
