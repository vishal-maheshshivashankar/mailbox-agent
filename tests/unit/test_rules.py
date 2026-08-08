from mailbox_agent.toolkit import rules


def test_normalize_sender_extracts_email_from_display_name():
    assert rules._normalize_sender("Some Shop <deals@shop.com>") == "deals@shop.com"
    assert rules._normalize_sender("plain@shop.com") == "plain@shop.com"
    assert rules._normalize_sender("Mixed CASE <Deals@Shop.COM>") == "deals@shop.com"


def test_learn_then_lookup_roundtrip():
    rules.learn("acct1", "Deals <deals@shop.com>", "promotions")
    assert rules.lookup("acct1", "deals@shop.com") == "promotions"
    assert rules.lookup("acct1", "unknown@nowhere.com") is None


def test_vip_roundtrip():
    assert rules.is_vip("acct1", "boss@work.com") is False
    rules.add_vip("acct1", "Boss <boss@work.com>")
    assert rules.is_vip("acct1", "boss@work.com") is True
