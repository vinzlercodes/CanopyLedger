"""Deterministic OpenAPI rendering for the versioned public contract."""

import json

from fastapi import FastAPI


def render_openapi_json(app: FastAPI) -> bytes:
    """Render the application schema with stable ordering and one trailing newline."""
    return (
        json.dumps(
            app.openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
