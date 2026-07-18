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
import socket
import subprocess
import sys
import time
from collections.abc import Sequence

from run_postgres_acceptance import (
    AcceptanceRunnerError,
    _bootstrap_roles,
    _remove_container,
    _start_disposable_database,
)
from sqlalchemy import create_engine

from canopyledger.demo.postgres import seed_demo_workspace


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


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
    parser.add_argument("--api-port", type=_port, default=8000)
    parser.add_argument("--web-port", type=_port, default=3000)
    return parser.parse_args(argv)


def _run_migrations(database_url: str) -> None:
    completed = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": database_url},
        check=False,
    )
    if completed.returncode != 0:
        raise AcceptanceRunnerError("database migration failed")


def _validate_serve_ports(*, api_port: int, web_port: int) -> None:
    if api_port == web_port:
        raise AcceptanceRunnerError("API and web ports must be different")
    for name, port in (("API", api_port), ("web", web_port)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                suggested_api_port = _suggest_available_port()
                suggested_web_port = _suggest_available_port()
                raise AcceptanceRunnerError(
                    f"{name} port {port} is already in use on 127.0.0.1. "
                    "Stop only the process you own or rerun: "
                    "make demo DEMO_ARGS="
                    f"'--api-port {suggested_api_port} --web-port {suggested_web_port}'"
                ) from exc


def _suggest_available_port() -> int:
    """Return an illustrative loopback port; it is not a reservation."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _web_command(*, web_port: int) -> list[str]:
    return [
        "npm",
        "--prefix",
        "apps/web",
        "run",
        "dev",
        "--",
        "--port",
        str(web_port),
        "--hostname",
        "127.0.0.1",
    ]


def _serve_environment(*, database_url: str, api_port: int, web_port: int) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": database_url,
        "CANOPYLEDGER_API_BASE_URL": f"http://127.0.0.1:{api_port}",
        "CANOPYLEDGER_DEMO_AUTH_ENABLED": "true",
        "CANOPYLEDGER_DEMO_SESSION_SECRET": secrets.token_hex(32),
        # A canonical demo must coexist with a developer's ordinary `next dev`
        # process, whose shared .next/dev lock otherwise rejects a second server.
        "CANOPYLEDGER_NEXT_DIST_DIR": ".next-demo",
    }


def _serve(*, database_url: str, api_port: int, web_port: int) -> int:
    environment = _serve_environment(
        database_url=database_url, api_port=api_port, web_port=web_port
    )
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
    web = subprocess.Popen(_web_command(web_port=web_port), env=environment)
    print(f"Canonical API: http://127.0.0.1:{api_port}")
    print(f"Canonical Reports UI: http://127.0.0.1:{web_port}/sign-in")
    print(
        "Use the synthetic approver role to view the approved report package. Press Ctrl-C to stop."
    )
    processes = (api, web)
    interrupted = False
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.1)
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
    failed = next(
        (process for process in processes if process.returncode not in (0, -signal.SIGTERM)),
        None,
    )
    if failed is not None:
        server_name = "API" if failed is api else "web"
        print(
            f"Canonical {server_name} server exited during startup (exit {failed.returncode}). "
            "A port may have become unavailable after preflight.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Provision/migrate/seed the complete M10 demo and optionally host its UI."""
    args = _parse_args(argv)
    if not args.no_serve:
        try:
            _validate_serve_ports(api_port=args.api_port, web_port=args.web_port)
        except AcceptanceRunnerError as error:
            print(f"Canonical demo cannot start: {error}", file=sys.stderr)
            return 1
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
