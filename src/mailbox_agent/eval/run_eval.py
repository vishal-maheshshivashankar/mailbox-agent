"""Classification quality eval: runs the real classifier against a
hand-labeled golden set and reports accuracy, per-category precision/recall,
and a confusion matrix.

This exists because a prompt or model change in toolkit/llm.py is otherwise
invisible until you notice your inbox got mis-sorted days later. Run this
BEFORE shipping a classifier change, not after - see docs/EVALUATION.md.

    mailbox-agent-eval
    mailbox-agent-eval --dataset path/to/your_own_labeled_emails.jsonl
    mailbox-agent-eval --threshold 0.9
"""

import argparse
import json
from importlib import resources

from mailbox_agent.eval.metrics import compute_metrics
from mailbox_agent.toolkit import llm
from mailbox_agent.toolkit.models import EmailSummary

DEFAULT_ACCURACY_THRESHOLD = 0.75


def load_dataset(path: str | None) -> list[dict]:
    if path:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    data = resources.files("mailbox_agent.eval").joinpath("golden_set.jsonl").read_text()
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def run(dataset_path: str | None = None) -> dict:
    rows = load_dataset(dataset_path)
    messages = [
        EmailSummary(
            id=str(i),
            thread_id=str(i),
            sender=r["sender"],
            subject=r["subject"],
            snippet=r["snippet"],
            date="",
        )
        for i, r in enumerate(rows)
    ]
    expected = [r["expected_category"] for r in rows]

    classifications = llm.classify_batch(messages)
    by_id = {c.message_id: c.category for c in classifications}
    predicted = [by_id.get(str(i), "other") for i in range(len(rows))]

    return compute_metrics(predicted, expected)


def print_report(metrics: dict) -> None:
    print(f"\nOverall accuracy: {metrics['accuracy']:.1%} ({metrics['correct']}/{metrics['total']})\n")
    print(f"{'category':<14}{'precision':<12}{'recall':<10}support")
    for cat, m in sorted(metrics["per_category"].items()):
        precision = f"{m['precision']:.0%}" if m["precision"] is not None else "n/a"
        recall = f"{m['recall']:.0%}" if m["recall"] is not None else "n/a"
        print(f"{cat:<14}{precision:<12}{recall:<10}{m['support']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", help="path to a .jsonl golden set; defaults to the bundled sample")
    parser.add_argument("--threshold", type=float, default=DEFAULT_ACCURACY_THRESHOLD)
    args = parser.parse_args()

    metrics = run(args.dataset)
    print_report(metrics)

    if metrics["accuracy"] < args.threshold:
        print(f"\nFAIL: accuracy {metrics['accuracy']:.1%} is below threshold {args.threshold:.0%}")
        raise SystemExit(1)
    print(f"\nPASS: accuracy meets {args.threshold:.0%} threshold")


if __name__ == "__main__":
    main()
