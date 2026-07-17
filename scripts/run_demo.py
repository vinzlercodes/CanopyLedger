"""Start the canonical M10 synthetic PostgreSQL/PostGIS report demo.

With no ``DATABASE_URL`` this command provisions a disposable local PostGIS
container, migrates it, seeds the complete governed workspace, and launches
the API plus web app.  Ctrl-C stops both processes and removes only that
disposable container.  Supplying ``DATABASE_URL`` leaves lifecycle ownership
with the caller.
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
from collections.abc import Sequence

from run_postgres_acceptance import (
    AcceptanceRunnerError,
    _bootstrap_roles,
    _remove_container,
    _start_disposable_database,
)
from sqlalchemy import create_engine

from canopyledger.demo.postgres import seed_demo_workspace


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help=(
            "Use a caller-managed PostgreSQL 17/PostGIS database instead of a disposable container."
        ),
    )
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help=(
            "Seed and verify the canonical package, then exit without starting API or web servers."
        ),
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3000)
    return parser.parse_args(argv)


def _run_migrations(database_url: str) -> None:
    completed = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": database_url},
        check=False,
    )
    if completed.returncode != 0:
        raise AcceptanceRunnerError("database migration failed")


def _serve(*, database_url: str, api_port: int, web_port: int) -> int:
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "CANOPYLEDGER_API_BASE_URL": f"http://127.0.0.1:{api_port}",
        "CANOPYLEDGER_DEMO_AUTH_ENABLED": "true",
        "CANOPYLEDGER_DEMO_SESSION_SECRET": secrets.token_hex(32),
    }
    api = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "canopyledger.demo.postgres:create_postgres_demo_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        env=environment,
    )
    web = subprocess.Popen(
        ["npm", "--prefix", "apps/web", "run", "dev", "--", "--port", str(web_port)],
        env=environment,
    )
    print(f"Canonical API: http://127.0.0.1:{api_port}")
    print(f"Canonical Reports UI: http://127.0.0.1:{web_port}/sign-in")
    print(
        "Use the synthetic approver role to view the approved report package. Press Ctrl-C to stop."
    )
    processes = (api, web)
    interrupted = False
    try:
        while all(process.poll() is None for process in processes):
            signal.pause()
    except KeyboardInterrupt:
        interrupted = True
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    if interrupted:
        return 0
    return 0 if all(process.returncode in (0, -signal.SIGTERM) for process in processes) else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Provision/migrate/seed the complete M10 demo and optionally host its UI."""
    args = _parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    container_name: str | None = None
    try:
        if database_url is None:
            container_name, database_url = _start_disposable_database()
            _bootstrap_roles(container_name)
            print("Using a fresh disposable PostgreSQL 17/PostGIS database.")
        else:
            print("Using the caller-managed DATABASE_URL for the canonical demo.")
        _run_migrations(database_url)
        engine = create_engine(database_url)
        try:
            seeded = seed_demo_workspace(engine)
        finally:
            engine.dispose()
        print("Canonical synthetic M10 workspace seeded.")
        print(f"Facility: {seeded.facility_id}")
        print(f"Snapshot: {seeded.snapshot_id}")
        print(f"Final decision: {seeded.decision_id}")
        print(f"Report: {seeded.report_id}")
        print(f"Report model: {seeded.report_model_digest}")
        for artifact_format, digest in sorted(seeded.artifact_digests.items()):
            print(f"{artifact_format} artifact: {digest}")
        if args.no_serve:
            return 0
        return _serve(database_url=database_url, api_port=args.api_port, web_port=args.web_port)
    except AcceptanceRunnerError as error:
        print(f"Canonical demo failed: {error}", file=sys.stderr)
        return 1
    finally:
        if container_name is not None:
            _remove_container(container_name)


if __name__ == "__main__":
    raise SystemExit(main())
