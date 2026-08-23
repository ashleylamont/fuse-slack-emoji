from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

import pytest
from hypothesis import given, strategies as st
from slack_emoji_fs.object_store.local_file_object_store import LocalFileObjectStore
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore
from slack_emoji_fs.object_store.object_store import ObjectStore


@dataclass(frozen=True)
class ObjectStoreTestSpec:
    name: str
    init_store: Callable[[], AbstractContextManager[ObjectStore]]

@contextmanager
def memory_store() -> Generator[ObjectStore, None, None]:
    yield MemoryObjectStore()

@contextmanager
def local_file_store() -> Generator[ObjectStore, None, None]:
    yield LocalFileObjectStore()

# This spec probably shouldn't be used to test a live slack-based object_store implementation
OBJECT_STORE_TEST_SPECS = [
    ObjectStoreTestSpec("MemoryObjectStore", memory_store),
    ObjectStoreTestSpec("LocalFileObjectStore", local_file_store),
]

@pytest.mark.parametrize("spec", OBJECT_STORE_TEST_SPECS, ids=lambda spec: spec.name)
def test_fresh_store_is_empty(spec: ObjectStoreTestSpec) -> None:
    """A newly initialized store contains no object IDs."""
    with spec.init_store() as store:
        assert store.list_ids() == []

@pytest.mark.parametrize("spec", OBJECT_STORE_TEST_SPECS, ids=lambda spec: spec.name)
@given(payload=st.binary(max_size=64_000))
def test_payload_round_trip(spec: ObjectStoreTestSpec, payload: bytes) -> None:
    """Stored bytes can be retrieved unchanged and their ID is listed."""
    with spec.init_store() as store:
        store.put("efs_dat_test", payload)

        assert store.get("efs_dat_test") == payload
        assert "efs_dat_test" in store.list_ids()

@pytest.mark.parametrize("spec", OBJECT_STORE_TEST_SPECS, ids=lambda spec: spec.name)
def test_duplicate_insertion_fails(spec: ObjectStoreTestSpec) -> None:
    """Inserting an existing ID does not silently overwrite its object."""
    with spec.init_store() as store:
        store.put("efs_dat_test", b"payload")

        with pytest.raises(Exception):
            store.put("efs_dat_test", b"payload")

@pytest.mark.parametrize("spec", OBJECT_STORE_TEST_SPECS, ids=lambda spec: spec.name)
def test_missing_object(spec: ObjectStoreTestSpec) -> None:
    """Looking up an absent ID returns the store's missing-object result."""
    with spec.init_store() as store:
        assert store.get("efs_dat_missing") is None
