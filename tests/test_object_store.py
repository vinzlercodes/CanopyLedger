"""Object-store port contract tests."""

from pathlib import Path

import pytest

from canopyledger.integrity.object_store import (
    ImmutableObjectConflict,
    InvalidObjectKey,
    LocalObjectStore,
    ObjectDigestMismatch,
)


def test_put_and_read_content_addressed_object(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    content = b"warehouse receipt evidence"

    reference = store.put(content)

    assert reference.key.startswith("sha256/")
    assert reference.digest.startswith("sha256:")
    assert reference.size_bytes == len(content)
    assert store.read(reference.key, expected_digest=reference.digest) == content


def test_republishing_same_content_is_idempotent(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    first = store.put(b"same evidence")
    second = store.put(b"same evidence")

    assert first == second


def test_existing_key_cannot_be_replaced(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    reference = store.put(b"original")

    with pytest.raises(ImmutableObjectConflict):
        store.put_at_key(reference.key, b"replacement")


@pytest.mark.parametrize("key", ["../secret", "/absolute", "safe/../../secret", "", "."])
def test_user_controlled_paths_are_rejected(tmp_path: Path, key: str) -> None:
    store = LocalObjectStore(tmp_path)

    with pytest.raises(InvalidObjectKey):
        store.read(key)


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    reference = store.put(b"evidence")

    with pytest.raises(ObjectDigestMismatch):
        store.read(reference.key, expected_digest="sha256:" + "0" * 64)
