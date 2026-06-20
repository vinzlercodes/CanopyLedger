"""Immutable object-store port with a local filesystem adapter."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ObjectStoreError(ValueError):
    """Base object-store contract error."""


class InvalidObjectKey(ObjectStoreError):
    """Raised when a key could escape the configured object-store root."""


class ImmutableObjectConflict(ObjectStoreError):
    """Raised when publication would replace different immutable content."""


class ObjectDigestMismatch(ObjectStoreError):
    """Raised when stored bytes do not match the expected digest."""


@dataclass(frozen=True)
class ObjectReference:
    key: str
    digest: str
    size_bytes: int


class LocalObjectStore:
    """Content-addressed, immutable local implementation of the ObjectStore port."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> ObjectReference:
        digest = _digest(content)
        key = f"sha256/{digest.removeprefix('sha256:')}"
        self.put_at_key(key, content)
        return ObjectReference(key=key, digest=digest, size_bytes=len(content))

    def put_at_key(self, key: str, content: bytes) -> ObjectReference:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = _digest(content)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".canopy-object-",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                existing = destination.read_bytes()
                if existing != content:
                    raise ImmutableObjectConflict(f"object key already published: {key}") from None
        finally:
            temporary_path.unlink(missing_ok=True)
        return ObjectReference(key=key, digest=digest, size_bytes=len(content))

    def read(self, key: str, *, expected_digest: str | None = None) -> bytes:
        content = self._path_for(key).read_bytes()
        actual_digest = _digest(content)
        if expected_digest is not None and actual_digest != expected_digest:
            raise ObjectDigestMismatch(
                f"object digest mismatch: expected {expected_digest}, got {actual_digest}"
            )
        return content

    def _path_for(self, key: str) -> Path:
        key_path = PurePosixPath(key)
        if (
            not key
            or key_path.is_absolute()
            or key_path in {PurePosixPath("."), PurePosixPath("..")}
            or any(part in {"", ".", ".."} for part in key_path.parts)
        ):
            raise InvalidObjectKey(f"invalid object key: {key!r}")
        candidate = self._root.joinpath(*key_path.parts)
        if not candidate.is_relative_to(self._root):
            raise InvalidObjectKey(f"object key escapes store root: {key!r}")
        return candidate


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
