from mailbox_agent.config import _parse_retention_policy


def test_parse_retention_policy_basic():
    policy = _parse_retention_policy("promotions:0,social:0,newsletters:365,other:0")
    assert policy == {"promotions": 0, "social": 0, "newsletters": 365, "other": 0}


def test_parse_retention_policy_ignores_blank_entries_and_whitespace():
    policy = _parse_retention_policy(" promotions : 0 ,, newsletters:365 ")
    assert policy == {"promotions": 0, "newsletters": 365}


def test_parse_retention_policy_lowercases_category_names():
    policy = _parse_retention_policy("Promotions:0")
    assert policy == {"promotions": 0}
