.PHONY: setup test test-database-roles lint typecheck openapi openapi-check verify

setup:
	uv sync --extra dev

test:
	uv run pytest

test-database-roles:
	bash tests/integration/test_database_roles.sh

lint:
	uv run ruff check .

typecheck:
	uv run mypy

openapi:
	uv run python scripts/export_openapi.py

openapi-check:
	uv run python scripts/export_openapi.py --check

verify: lint typecheck openapi-check test
