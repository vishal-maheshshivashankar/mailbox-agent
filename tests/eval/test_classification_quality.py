"""Calls the real Gemini API against the golden set - costs a few cents and
needs GEMINI_API_KEY set to a real key. Excluded from the default `pytest`
run (see pyproject.toml addopts); run explicitly:

    pytest -m eval
"""

import pytest

from mailbox_agent.eval.run_eval import DEFAULT_ACCURACY_THRESHOLD, run


@pytest.mark.eval
def test_golden_set_accuracy_meets_threshold():
    metrics = run()
    assert metrics["accuracy"] >= DEFAULT_ACCURACY_THRESHOLD, (
        f"accuracy {metrics['accuracy']:.1%} below {DEFAULT_ACCURACY_THRESHOLD:.0%} "
        f"threshold; confusion matrix: {metrics['confusion']}"
    )
