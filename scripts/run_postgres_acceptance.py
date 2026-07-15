"""Run the PostgreSQL acceptance suite against a fresh disposable PostGIS database.

When DATABASE_URL is supplied, the caller owns provisioning and this runner uses that database.
Otherwise it creates an isolated Docker container, bootstraps the capability roles, runs the
complete migration/drift/test gate, and always removes the container before returning.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGIS_IMAGE = "postgis/postgis:17-3.5-alpine"
POSTGRES_PASSWORD = "canopyledger-test"
POSTGRES_DATABASE = "canopyledger"
POSTGRES_USER = "postgres"
STARTUP_TIMEOUT_SECONDS = 45


class AcceptanceRunnerError(RuntimeError):
    """Raised when the disposable PostgreSQL acceptance environment cannot start."""


def _run(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        cwd=PROJECT_ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=capture_output,
    )


def _require_success(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> None:
    completed = _run(command, env=env, input_text=input_text)
    if completed.returncode != 0:
        raise AcceptanceRunnerError(f"command failed: {' '.join(command)}")


def _start_disposable_database() -> tuple[str, str]:
    container_name = f"canopyledger-postgres-acceptance-{secrets.token_hex(5)}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        host_port = port_probe.getsockname()[1]
    created = _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--env",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "--env",
            f"POSTGRES_DB={POSTGRES_DATABASE}",
            "--publish",
            f"127.0.0.1:{host_port}:5432",
            POSTGIS_IMAGE,
        ],
        capture_output=True,
    )
    if created.returncode != 0:
        raise AcceptanceRunnerError(
            "could not start the disposable PostGIS container; install and start Docker, "
            "or provide DATABASE_URL for a disposable PostgreSQL 17/PostGIS database"
        )

    try:
        for _ in range(STARTUP_TIMEOUT_SECONDS * 2):
            ready = _run(
                [
                    "docker",
                    "exec",
                    container_name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    POSTGRES_USER,
                    "-d",
                    POSTGRES_DATABASE,
                ],
                capture_output=True,
            )
            if ready.returncode == 0:
                database_url = (
                    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@127.0.0.1:{host_port}/"
                    f"{POSTGRES_DATABASE}"
                )
                return container_name, database_url
            time.sleep(0.5)
    except BaseException:
        _remove_container(container_name)
        raise

    _remove_container(container_name)
    raise AcceptanceRunnerError("timed out waiting for the disposable PostGIS database")


def _bootstrap_roles(container_name: str) -> None:
    roles_script = (PROJECT_ROOT / "database/bootstrap/roles.sql").read_text(encoding="utf-8")
    _require_success(
        [
            "docker",
            "exec",
            "-i",
            container_name,
            "psql",
            "-U",
            POSTGRES_USER,
            "-d",
            POSTGRES_DATABASE,
            "-v",
            f"DBNAME={POSTGRES_DATABASE}",
        ],
        input_text=roles_script,
    )


def _remove_container(container_name: str) -> None:
    _run(["docker", "rm", "--force", container_name], capture_output=True)


def _run_acceptance(database_url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url}
    _require_success(["uv", "run", "alembic", "upgrade", "head"], env=environment)
    _require_success(["uv", "run", "alembic", "check"], env=environment)
    _require_success(["uv", "run", "pytest", "-m", "postgres", "-q"], env=environment)


def main() -> int:
    external_database_url = os.environ.get("DATABASE_URL")
    if external_database_url:
        print("Using caller-provided DATABASE_URL for PostgreSQL acceptance.")
        try:
            _run_acceptance(external_database_url)
        except AcceptanceRunnerError as error:
            print(f"PostgreSQL acceptance failed: {error}", file=sys.stderr)
            return 1
        return 0

    container_name: str | None = None
    try:
        container_name, database_url = _start_disposable_database()
        print("Using a fresh disposable PostGIS 17 database for PostgreSQL acceptance.")
        _bootstrap_roles(container_name)
        _run_acceptance(database_url)
    except AcceptanceRunnerError as error:
        print(f"PostgreSQL acceptance failed: {error}", file=sys.stderr)
        return 1
    finally:
        if container_name is not None:
            _remove_container(container_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
