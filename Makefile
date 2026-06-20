.PHONY: setup test lint typecheck verify

setup:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy

verify: lint typecheck test

