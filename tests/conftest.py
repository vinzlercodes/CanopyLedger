"""Top-level test-suite guardrails."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Reject a false-green PostgreSQL acceptance invocation without a database."""
    if config.getoption("markexpr") == "postgres" and not os.environ.get("DATABASE_URL"):
        raise pytest.UsageError(
            "PostgreSQL acceptance requires DATABASE_URL. "
            "Run `make test-m1a-postgres` to provision a fresh disposable PostGIS database."
        )
