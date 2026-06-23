"""PostgreSQL integration-test fixtures."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if value is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> None:
    completed = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        check=False,
        capture_output=True,
        env={**os.environ, "DATABASE_URL": database_url},
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(completed.stderr or completed.stdout)


@pytest.fixture(scope="session")
def database_engine(database_url: str, migrated_database: None) -> Iterator[Engine]:
    del migrated_database
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def connection(database_engine: Engine) -> Iterator[Connection]:
    with database_engine.connect() as database_connection:
        yield database_connection
