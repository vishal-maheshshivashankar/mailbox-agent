from mailbox_agent.toolkit.drive import _safe_name
from mailbox_agent.toolkit.gmail import _header


def test_header_lookup_is_case_insensitive():
    headers = [{"name": "From", "value": "a@b.com"}, {"name": "Subject", "value": "Hi"}]
    assert _header(headers, "from") == "a@b.com"
    assert _header(headers, "SUBJECT") == "Hi"
    assert _header(headers, "missing") == ""


def test_safe_name_strips_unsafe_characters_and_truncates():
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-")
    result = _safe_name("Hello, World! / <script>")
    assert set(result) <= allowed

    assert _safe_name("x" * 200) == "x" * 60
    assert _safe_name("!!!") == "untitled"
