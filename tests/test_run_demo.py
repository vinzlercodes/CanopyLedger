"""Demo server startup fails before database lifecycle work when ports are unusable."""

from __future__ import annotations

import importlib
import socket
from pathlib import Path

import pytest


@pytest.fixture
def run_demo(monkeypatch: pytest.MonkeyPatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return importlib.import_module("run_demo")


def test_serve_port_preflight_rejects_an_occupied_web_port_before_database_lifecycle(
    run_demo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    _, occupied_port = listener.getsockname()
    monkeypatch.setattr(
        run_demo,
        "_start_disposable_database",
        lambda: pytest.fail("database lifecycle must not start after port preflight failure"),
    )
    suggested_ports = iter((3010, 3011))
    monkeypatch.setattr(
        run_demo,
        "_suggest_available_port",
        lambda: next(suggested_ports),
        raising=False,
    )
    try:
        assert run_demo.main(["--web-port", str(occupied_port)]) == 1
    finally:
        listener.close()

    error_output = capsys.readouterr().err
    assert f"web port {occupied_port} is already in use on 127.0.0.1" in error_output
    assert "--api-port 3010 --web-port 3011" in error_output


def test_serve_port_preflight_rejects_duplicate_listener_ports(run_demo) -> None:
    with pytest.raises(run_demo.AcceptanceRunnerError, match="must be different"):
        run_demo._validate_serve_ports(api_port=8123, web_port=8123)


@pytest.mark.parametrize("port", ("0", "-1", "65536"))
def test_argument_parser_rejects_invalid_listener_ports(run_demo, port: str) -> None:
    with pytest.raises(SystemExit):
        run_demo._parse_args(["--api-port", port])


def test_web_command_binds_next_to_the_printed_loopback_origin(run_demo) -> None:
    command = run_demo._web_command(web_port=3010)

    assert command[-4:] == ["--port", "3010", "--hostname", "127.0.0.1"]


def test_demo_web_environment_uses_an_isolated_next_dev_cache(run_demo) -> None:
    environment = run_demo._serve_environment(
        database_url="postgresql://example", api_port=8010, web_port=3010
    )

    assert environment["CANOPYLEDGER_NEXT_DIST_DIR"] == ".next-demo"


def test_make_demo_forwards_explicit_port_overrides() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()

    assert "uv run python scripts/run_demo.py $(DEMO_ARGS)" in makefile
