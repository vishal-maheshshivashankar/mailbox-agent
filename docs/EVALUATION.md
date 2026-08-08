# Evaluating the classifier

Unit tests check that the *code* does what it's supposed to (the graph
wires together, labels get applied, the interrupt/resume cycle doesn't
double-fire side effects). None of that tells you whether the *model* is
any good at the actual job - correctly guessing an email's category from
its sender/subject/snippet. That's a different kind of test, and it's the
piece most people skip when they first build an LLM feature, then find out
the hard way when a prompt tweak silently makes things worse.

## Why exact-match accuracy, not "LLM-as-judge"

LLM-as-judge (asking a second model to grade the first model's output) earns
its keep on open-ended generation, where there's no single correct answer to
compare against - summaries, chat replies, code review comments. This task
isn't that: every email has exactly one correct category out of a fixed set
of seven. That means plain **ground-truth comparison** - a human-labeled
answer key, exact-match scoring - is both simpler and more reliable than an
LLM judge would be here. Use the simplest eval method the task shape
actually calls for; don't reach for LLM-as-judge by default.

## What's here

- `src/mailbox_agent/eval/golden_set.jsonl` - 28 hand-labeled examples, 4 per
  category, synthetic but representative (realistic sender/subject/snippet
  triples, not real mail - see below for why that matters).
- `src/mailbox_agent/eval/metrics.py` - accuracy, per-category precision/
  recall, and a confusion matrix. Plain counting, no eval framework needed
  for a fixed-label classification task.
- `src/mailbox_agent/eval/run_eval.py` - loads a dataset, runs the real
  classifier (`toolkit/llm.py`) against it, prints the report, exits
  non-zero if accuracy is below threshold (default 75%).
- `tests/eval/test_classification_quality.py` - the same thing as a pytest,
  marked `@pytest.mark.eval` and excluded from the default `pytest` run
  (see `addopts` in `pyproject.toml`) because it calls the real Gemini API -
  costs a small amount of money and needs `GEMINI_API_KEY` set for real.

## Running it

```bash
mailbox-agent-eval                          # bundled synthetic set, threshold 75%
mailbox-agent-eval --dataset my_emails.jsonl --threshold 0.9
pytest -m eval                              # same thing, as a pass/fail test
```

## The synthetic dataset is a starting point, not the goal

28 synthetic examples can tell you the classifier isn't badly broken. They
can't tell you it works well on *your* mailbox - your actual senders, your
actual subject-line conventions, the specific newsletters and receipts you
actually get. **Replace/grow this dataset with real examples from your own
inbox** (this is Phase 0 in ARCHITECTURE.md): pull ~50-100 real emails,
label them by hand, drop them in a `.jsonl` file in the same shape, and run
`mailbox-agent-eval --dataset your_file.jsonl`. That number will mean
something the synthetic one can't.

## When to run this

Before shipping any change to `toolkit/llm.py` - a prompt edit, a model
swap, a batch-size change - run the eval and compare the report to what you
had before. This is a regression gate for a component that unit tests
structurally cannot cover (a unit test can assert "the LLM was called with
these arguments," never "the LLM's answer was right").

It's deliberately **not** wired into a blocking CI job that runs on every
commit: it costs money and calls a live API on every run, which is a bad
default for something that gates merges automatically at low volume/budget.
The honest middle ground - and the one many small teams actually use - is a
manual or `workflow_dispatch`-triggered CI job (see `.github/workflows/`)
that a human runs deliberately before merging a classifier change, not a
required check on every push.

## Growing this further

- **More categories of hard cases**: ambiguous senders (a personal email
  from a company alias), non-English subject lines, forwarded mail.
- **Regression cases**: every time a real misclassification gets corrected
  via Telegram, consider adding that exact example to the golden set so it
  can never silently regress again.
- **Per-category thresholds**: right now there's one overall accuracy gate.
  If "important" mail getting misclassified as "promotions" matters more
  than the reverse, that asymmetry belongs in the eval as a stricter
  per-category recall requirement on `important`, not just an overall score.
