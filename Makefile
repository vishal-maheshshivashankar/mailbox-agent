.PHONY: install test test-eval lint format typecheck check run sort sweep bot clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/unit -v

test-eval:
	pytest -m eval -v

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

check: lint typecheck test

run:
	mailbox-agent-serve

sort:
	mailbox-agent-sort

sweep:
	mailbox-agent-sweep

bot:
	mailbox-agent-telegram-bot

clean:
	find . -name "__pycache__" -not -path "./.venv/*" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "./.venv/*" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	rm -rf src/*.egg-info build dist
