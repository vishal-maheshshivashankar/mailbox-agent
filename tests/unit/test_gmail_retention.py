"""Verifies find_retention_candidates actually respects a per-category
policy dict - the core of the "some labels delete immediately, some wait
a year, some never" redesign - rather than just trusting it compiles.
"""

from unittest.mock import patch

from mailbox_agent.toolkit.gmail import find_retention_candidates
from mailbox_agent.toolkit.models import EmailSummary


def test_find_retention_candidates_only_queries_categories_in_policy():
    queries: list[str] = []

    def fake_list_messages_page(service, query, page_token, max_results):
        queries.append(query)
        if "AI/Promotions" in query:
            return {"messages": [{"id": "p1"}], "nextPageToken": None}
        if "AI/Newsletters" in query:
            return {"messages": [{"id": "n1"}], "nextPageToken": None}
        return {"messages": [], "nextPageToken": None}

    def fake_get_message_summary(service, msg_id):
        return EmailSummary(id=msg_id, thread_id=msg_id, sender="x@y.com", subject="s", snippet="s", date="d")

    # "not_a_real_category" isn't in CATEGORY_LABELS - must be skipped, not KeyError.
    policy = {"promotions": 0, "newsletters": 365, "not_a_real_category": 10}

    with (
        patch("mailbox_agent.toolkit.gmail._list_messages_page", side_effect=fake_list_messages_page),
        patch("mailbox_agent.toolkit.gmail.get_message_summary", side_effect=fake_get_message_summary),
    ):
        results = find_retention_candidates(service=object(), account_id="acct", retention_policy=policy)

    assert {r.id for r in results} == {"p1", "n1"}
    assert not any("not_a_real_category" in q for q in queries)
    # Starred/important exclusion is unconditional, for every queried category.
    assert all("-is:starred -is:important" in q for q in queries)


def test_find_retention_candidates_skips_categories_absent_from_policy():
    """important/receipts/personal/statements/e_mandate aren't in the default
    policy at all - confirm they're never queried, i.e. genuinely
    untouchable by retention, not just unlikely."""
    queries: list[str] = []

    def fake_list_messages_page(service, query, page_token, max_results):
        queries.append(query)
        return {"messages": [], "nextPageToken": None}

    with patch("mailbox_agent.toolkit.gmail._list_messages_page", side_effect=fake_list_messages_page):
        find_retention_candidates(service=object(), account_id="acct", retention_policy={"promotions": 0})

    assert len(queries) == 1
    assert "AI/Promotions" in queries[0]
