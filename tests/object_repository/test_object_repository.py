import time
from typing import TypedDict

import pytest

from slack_emoji_fs.file_system_models.data_chunk_object import DataChunkObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.errors import (
    InvalidNamespaceError,
    ObjectNotFoundError,
    WrongObjectTypeError,
)
from slack_emoji_fs.object_repository.object_ids import ObjectIdV1Standard
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_repository.object_store_accessor import ObjectStoreAccessor
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore


type FileSystemObjectModel = (
    DataChunkObject
    | DirectoryEntryObject
    | DirectoryInodeObject
    | FileInodeObject
    | RootObject
)


class _InodeMetadata(TypedDict):
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int


def _inode_metadata() -> _InodeMetadata:
    return {"mode": 0o644, "uid": 1000, "gid": 1000, "mtime": 1, "ctime": 2}


@pytest.fixture
def repository() -> ObjectRepository:
    return ObjectRepository(MemoryObjectStore(), namespace="tests")


@pytest.mark.parametrize(
    ("fs_object", "loader_name"),
    [
        (DataChunkObject(data=b"data"), "load_data_chunk_object"),
        (DirectoryEntryObject(entries={}), "load_dirent_object"),
        (FileInodeObject(chunks=[], size=0, **_inode_metadata()), "load_inode_object"),
        (DirectoryInodeObject(dirent_object_id="dirent-id", **_inode_metadata()), "load_inode_object"),
        (RootObject(parent_root_id=None, root_inode_id="root-inode-id"), "load_root_object"),
    ],
)
def test_repository_stores_and_loads_each_typed_model(
    repository: ObjectRepository,
    fs_object: FileSystemObjectModel,
    loader_name: str,
) -> None:
    """Stored models can be loaded through their matching typed repository API."""
    object_id = repository.store_fs_object(fs_object)
    loader = getattr(repository, loader_name)

    assert loader(object_id) == fs_object
    info = ObjectIdV1Standard.parse_id(object_id)
    assert info.namespace == "tests"


def test_repository_reports_missing_objects() -> None:
    """Loading an absent object reports that it cannot be found."""
    repository = ObjectRepository(MemoryObjectStore(), namespace="tests")

    with pytest.raises(ObjectNotFoundError):
        repository.load_data_chunk_object("efs_v1_tests_dat_0_missing")


def test_repository_reports_wrong_typed_loads(repository: ObjectRepository) -> None:
    """Loading an object through an incompatible typed API is rejected."""
    object_id = repository.store_fs_object(DataChunkObject(data=b"data"))

    with pytest.raises(WrongObjectTypeError, match="non-root"):
        repository.load_root_object(object_id)


def test_repository_rejects_a_non_alphabetic_namespace() -> None:
    """Repository namespaces must use the permitted alphabetic form."""
    with pytest.raises(InvalidNamespaceError):
        ObjectRepository(MemoryObjectStore(), namespace="test-namespace")


def test_object_id_generation_round_trips_through_the_v1_parser() -> None:
    """Generated V1 IDs preserve type, namespace, timestamp, and unique identity."""
    before = time.time()
    object_id = ObjectIdV1Standard.generate_id("DAT", "tests")
    after = time.time()

    info = ObjectIdV1Standard.parse_id(object_id)
    assert info.id_version == 1
    assert info.namespace == "tests"
    assert info.object_type == "DAT"
    # V1 serializes milliseconds, so parsing can round down by just under 1 ms.
    assert before - 0.001 <= info.timestamp <= after
    assert len(info.unique_id) == 32


@pytest.mark.parametrize(
    ("object_id", "namespace", "expected"),
    [
        ("efs_v1_tests_dat_1_identifier", "tests", True),
        ("efs_v1_tests_dat_1_identifier", "other", False),
        ("not_efs_v1_tests_dat_1_identifier", "tests", False),
    ],
)
def test_object_id_validation_screens_ids_by_namespace(
    object_id: str,
    namespace: str,
    expected: bool,
) -> None:
    """ID validation accepts only well-formed IDs belonging to the requested namespace."""
    assert ObjectIdV1Standard.is_valid_id(object_id, namespace) is expected


def test_accessor_filters_namespace_and_sorts_timestamps() -> None:
    """Accessor queries exclude other namespaces and order matching IDs by timestamp."""
    store = MemoryObjectStore()
    older_root = "efs_v1_tests_rot_1000_older"
    newer_root = "efs_v1_tests_rot_3000_newer"
    other_namespace = "efs_v1_other_rot_5000_elsewhere"
    for object_id in (newer_root, other_namespace, older_root):
        store.put(object_id, b"payload")

    object_ids = (
        ObjectStoreAccessor(store, "tests")
        .query()
        .sort_by_timestamp(descending=False)
        .object_ids()
    )

    assert object_ids == [older_root, newer_root]


def test_accessor_filters_by_the_public_object_type_literal() -> None:
    """Accessor type filtering accepts the public object-type spelling and excludes others."""
    store = MemoryObjectStore()
    root_id = "efs_v1_tests_rot_1000_root"
    data_id = "efs_v1_tests_dat_2000_data"
    store.put(root_id, b"root")
    store.put(data_id, b"data")

    assert ObjectStoreAccessor(store, "tests").query().with_object_type("ROT").object_ids() == [root_id]


@pytest.mark.parametrize("length, expected_chunk_count", [
    (0, 0),
    (MAX_DATA_CHUNK_PAYLOAD_SIZE - 1, 1),
    (MAX_DATA_CHUNK_PAYLOAD_SIZE, 1),
    (MAX_DATA_CHUNK_PAYLOAD_SIZE + 1, 2),
])
def test_repository_splits_data_at_chunk_boundaries(
    repository: ObjectRepository,
    length: int,
    expected_chunk_count: int,
) -> None:
    """Data is split into correctly sized chunks and reconstructs the original bytes."""
    data = b"a" * length
    chunk_ids = repository.store_and_split_data_chunks(data)

    assert len(chunk_ids) == expected_chunk_count
    assert b"".join(repository.load_data_chunk_object(chunk_id).data for chunk_id in chunk_ids) == data
