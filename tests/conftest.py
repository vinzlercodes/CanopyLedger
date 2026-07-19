"""Top-level test-suite guardrails and synthetic API configuration."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("CANOPYLEDGER_DEMO_AUTH_ENABLED", "true")


def pytest_configure(config: pytest.Config) -> None:
    """Reject a false-green PostgreSQL acceptance invocation without a database."""
    if config.getoption("markexpr") == "postgres" and not os.environ.get("DATABASE_URL"):
        raise pytest.UsageError(
            "PostgreSQL acceptance requires DATABASE_URL. "
            "Run `make test-m1a-postgres` to provision a fresh disposable PostGIS database."
        )
