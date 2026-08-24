import pytest

from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore
from slack_emoji_fs.tree_operations.errors import EntryExistsError
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_writer import TreeWriter


@pytest.fixture
def filesystem() -> FileSystem:
    repository = ObjectRepository(MemoryObjectStore(), "test")
    navigator = TreeNavigator(repository)
    return FileSystem.create_from_latest_root_or_new(repository, navigator, TreeWriter(repository, navigator))


def test_mutations_adopt_returned_snapshot_and_reads_use_current_snapshot(filesystem: FileSystem) -> None:
    """Successful mutations advance the facade snapshot used by subsequent reads."""
    initial_root_id = filesystem.current_snapshot.root_object_id

    assert filesystem.current_snapshot.root_object_id == initial_root_id
    filesystem.create_directory("/docs", mode=0o755, uid=1000, gid=1000)
    after_directory = filesystem.current_snapshot.root_object_id
    filesystem.create_file("/docs/readme", mode=0o644, uid=1000, gid=1000, contents=b"one")
    filesystem.write_file("/docs/readme", b"two")
    filesystem.truncate_file("/docs/readme", 5)

    assert after_directory != initial_root_id
    assert filesystem.current_snapshot.root_object_id != after_directory
    assert filesystem.list_directory("/docs") == ("readme",)
    assert filesystem.read_file("/docs/readme") == b"two\0\0"


def test_failed_mutation_keeps_current_snapshot(filesystem: FileSystem) -> None:
    """A failed mutation leaves the facade pointed at its prior snapshot."""
    filesystem.create_file("/note", mode=0o644, uid=0, gid=0)
    before_failure = filesystem.current_snapshot.root_object_id

    with pytest.raises(EntryExistsError):
        filesystem.create_file("/note", mode=0o644, uid=0, gid=0)

    assert filesystem.current_snapshot.root_object_id == before_failure
    assert filesystem.read_file("/note") == b""


def test_replace_file_replaces_all_contents_in_one_snapshot(filesystem: FileSystem) -> None:
    """Replaces a file including a shorter length without preserving its old tail."""
    filesystem.create_file(
        "/note",
        mode=0o644,
        uid=0,
        gid=0,
        contents=b"old contents",
    )
    before_replace = filesystem.current_snapshot.root_object_id

    filesystem.replace_file("/note", b"new")

    assert filesystem.current_snapshot.root_object_id != before_replace
    assert filesystem.read_file("/note") == b"new"


def test_try_resolve_returns_none_for_missing_or_non_directory_path(filesystem: FileSystem) -> None:
    """Best-effort resolution returns none for missing paths and traversal through files."""
    filesystem.create_file("/file", mode=0o644, uid=0, gid=0)

    assert filesystem.try_resolve("/missing") is None
    assert filesystem.try_resolve("/file/child") is None
    assert filesystem.try_resolve("/file") is not None
