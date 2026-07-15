.PHONY: setup test test-database-roles test-m1a-postgres migrate migrate-check lint typecheck openapi openapi-check typescript-client-check fit-credit-reference-model document-extraction-benchmark verify

setup:
	uv sync --extra dev

test:
	uv run pytest

test-database-roles:
	bash tests/integration/test_database_roles.sh

test-m1a-postgres:
	uv run python scripts/run_postgres_acceptance.py

migrate:
	uv run alembic upgrade head

migrate-check:
	uv run alembic check

lint:
	uv run ruff check .

typecheck:
	uv run mypy

openapi:
	uv run python scripts/export_openapi.py

openapi-check:
	uv run python scripts/export_openapi.py --check

typescript-client-check:
	npm --prefix typescript run client:check

fit-credit-reference-model:
	uv run python scripts/fit_credit_reference_model.py

document-extraction-benchmark:
	uv run python scripts/run_document_extraction_benchmark.py

verify: lint typecheck openapi-check typescript-client-check test
