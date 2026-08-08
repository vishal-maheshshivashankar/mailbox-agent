"""Tests the eval *machinery* itself (metrics math, dataset loading) without
calling the real LLM - that part is covered separately by tests/eval/,
which is excluded from the default run since it costs money and needs a
real API key.
"""

from mailbox_agent.eval.metrics import compute_metrics
from mailbox_agent.eval.run_eval import load_dataset


def test_compute_metrics_perfect_score():
    m = compute_metrics(["promotions", "personal"], ["promotions", "personal"])
    assert m["accuracy"] == 1.0
    assert m["per_category"]["promotions"]["precision"] == 1.0
    assert m["per_category"]["promotions"]["recall"] == 1.0


def test_compute_metrics_catches_confusion():
    # 1 of 2 "promotions" mislabeled as "newsletters"; "personal" correct.
    predicted = ["newsletters", "promotions", "personal"]
    expected = ["promotions", "promotions", "personal"]
    m = compute_metrics(predicted, expected)

    assert m["accuracy"] == 2 / 3
    assert m["per_category"]["promotions"]["recall"] == 0.5  # 1 of 2 actual promotions caught
    assert m["per_category"]["newsletters"]["precision"] == 0.0  # its 1 prediction was wrong
    assert m["confusion"]["promotions"]["newsletters"] == 1


def test_bundled_golden_set_loads_and_has_expected_shape():
    rows = load_dataset(None)
    assert len(rows) >= 20
    for row in rows:
        assert {"sender", "subject", "snippet", "expected_category"} <= row.keys()
