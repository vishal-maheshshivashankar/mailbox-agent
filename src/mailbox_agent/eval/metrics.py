"""Accuracy / per-category precision & recall / confusion matrix for a
classification eval. Plain counting - no framework needed for a
fixed-label-set classification task like this one."""

from collections import Counter, defaultdict
from collections.abc import Sequence


def compute_metrics(predicted: Sequence[str], expected: Sequence[str]) -> dict:
    if len(predicted) != len(expected):
        raise ValueError(f"predicted ({len(predicted)}) and expected ({len(expected)}) length mismatch")

    total = len(expected)
    correct = sum(p == e for p, e in zip(predicted, expected, strict=True))

    # confusion[actual][predicted] = count
    confusion: dict[str, Counter] = defaultdict(Counter)
    for p, e in zip(predicted, expected, strict=True):
        confusion[e][p] += 1

    categories = sorted(set(expected) | set(predicted))
    per_category = {}
    for cat in categories:
        tp = confusion[cat][cat]
        fn = sum(count for other, count in confusion[cat].items() if other != cat)
        fp = sum(confusion[other][cat] for other in categories if other != cat)
        support = sum(confusion[cat].values())
        per_category[cat] = {
            "precision": tp / (tp + fp) if (tp + fp) else None,
            "recall": tp / (tp + fn) if (tp + fn) else None,
            "support": support,
        }

    return {
        "accuracy": correct / total if total else 0.0,
        "total": total,
        "correct": correct,
        "per_category": per_category,
        "confusion": {actual: dict(preds) for actual, preds in confusion.items()},
    }
