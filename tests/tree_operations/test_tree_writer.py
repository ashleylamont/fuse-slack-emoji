import pytest

from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore
from slack_emoji_fs.tree_operations.errors import (
    DirectoryNotEmptyError,
    EntryExistsError,
    InvalidFileRangeError,
    IsDirectoryError,
    NotDirectoryError,
    RootOperationError,
)
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_reader import TreeReader
from slack_emoji_fs.tree_operations.tree_snapshot import TreeSnapshot
from slack_emoji_fs.tree_operations.tree_writer import TreeWriter


@pytest.fixture
def tree_components() -> tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]:
    repository = ObjectRepository(MemoryObjectStore(), "test")
    navigator = TreeNavigator(repository)
    writer = TreeWriter(repository, navigator)
    filesystem = FileSystem.create_from_latest_root_or_new(repository, navigator, writer)
    return repository, navigator, writer, filesystem.current_snapshot


def _reader(repository: ObjectRepository, navigator: TreeNavigator, snapshot: TreeSnapshot) -> TreeReader:
    return TreeReader(repository, navigator, snapshot)


def test_create_file_publishes_new_snapshot_without_changing_base(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Creating a file yields a new snapshot while leaving the base snapshot intact."""
    repository, navigator, writer, base = tree_components

    changed = writer.create_file(base, "/hello", mode=0o644, uid=1000, gid=1000, contents=b"hello")

    assert changed.root_object_id != base.root_object_id
    assert changed.parent_root_id == base.root_object_id
    assert _reader(repository, navigator, changed).read_file("/hello") == b"hello"
    assert _reader(repository, navigator, base).list_directory("/") == ()


def test_create_directory_and_nested_file(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Directories can be created and then used as parents for new files."""
    repository, navigator, writer, base = tree_components

    with_directory = writer.create_directory(base, "/docs", mode=0o755, uid=1, gid=2)
    changed = writer.create_file(with_directory, "/docs/readme", mode=0o600, uid=1, gid=2, contents=b"v1")

    reader = _reader(repository, navigator, changed)
    assert reader.list_directory("/") == ("docs",)
    assert reader.list_directory("/docs") == ("readme",)
    assert reader.read_file("/docs/readme") == b"v1"


def test_create_rejects_existing_name(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Creation rejects a name that already exists in its parent directory."""
    _, _, writer, base = tree_components
    changed = writer.create_file(base, "/exists", mode=0o644, uid=0, gid=0)

    with pytest.raises(EntryExistsError):
        writer.create_directory(changed, "/exists", mode=0o755, uid=0, gid=0)


def test_write_overwrites_and_preserves_base_snapshot(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Writes replace bytes in a new snapshot without changing prior file contents."""
    repository, navigator, writer, base = tree_components
    original = writer.create_file(base, "/note", mode=0o644, uid=0, gid=0, contents=b"abcdef")

    changed = writer.write_file(original, "/note", b"XYZ", offset=2)

    assert _reader(repository, navigator, original).read_file("/note") == b"abcdef"
    assert _reader(repository, navigator, changed).read_file("/note") == b"abXYZf"


def test_truncate_shrinks_extends_and_is_noop_at_same_size(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Truncation shrinks, zero-extends, and preserves the snapshot at equal size."""
    repository, navigator, writer, base = tree_components
    original = writer.create_file(base, "/note", mode=0o644, uid=0, gid=0, contents=b"abcdef")

    shortened = writer.truncate_file(original, "/note", 3)
    extended = writer.truncate_file(shortened, "/note", 6)

    assert _reader(repository, navigator, shortened).read_file("/note") == b"abc"
    assert _reader(repository, navigator, extended).read_file("/note") == b"abc\0\0\0"
    assert writer.truncate_file(extended, "/note", 6) is extended


def test_chmod_is_noop_when_mode_already_matches(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Applying the existing mode avoids publishing an identical filesystem snapshot."""
    _, _, writer, base = tree_components
    snapshot = writer.create_file(base, "/note", mode=0o644, uid=0, gid=0)

    assert writer.chmod(snapshot, "/note", 0o100644) is snapshot


@pytest.mark.parametrize("operation", ["write", "truncate"])
def test_negative_file_ranges_are_rejected(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot], operation: str) -> None:
    """Writing and truncating reject negative byte offsets or target sizes."""
    _, _, writer, base = tree_components
    snapshot = writer.create_file(base, "/note", mode=0o644, uid=0, gid=0)

    with pytest.raises(InvalidFileRangeError):
        if operation == "write":
            writer.write_file(snapshot, "/note", b"x", offset=-1)
        else:
            writer.truncate_file(snapshot, "/note", -1)


def test_unlink_and_remove_directory_validate_type_and_emptiness(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Unlink rejects directories; rmdir rejects files and non-empty directories, but removes empty ones."""
    repository, navigator, writer, base = tree_components
    snapshot = writer.create_directory(base, "/empty", mode=0o755, uid=0, gid=0)
    snapshot = writer.create_directory(snapshot, "/full", mode=0o755, uid=0, gid=0)
    snapshot = writer.create_file(snapshot, "/full/file", mode=0o644, uid=0, gid=0)

    with pytest.raises(IsDirectoryError):
        writer.unlink_file(snapshot, "/empty")
    with pytest.raises(NotDirectoryError):
        writer.remove_directory(snapshot, "/full/file")
    with pytest.raises(DirectoryNotEmptyError):
        writer.remove_directory(snapshot, "/full")

    without_file = writer.unlink_file(snapshot, "/full/file")
    changed = writer.remove_directory(without_file, "/empty")
    assert _reader(repository, navigator, changed).list_directory("/") == ("full",)


def test_rename_within_and_across_parents(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Rename moves an existing inode within one directory or between directories."""
    repository, navigator, writer, base = tree_components
    snapshot = writer.create_directory(base, "/one", mode=0o755, uid=0, gid=0)
    snapshot = writer.create_directory(snapshot, "/two", mode=0o755, uid=0, gid=0)
    snapshot = writer.create_file(snapshot, "/one/file", mode=0o644, uid=0, gid=0, contents=b"data")

    renamed = writer.rename(snapshot, "/one/file", "/one/renamed")
    moved = writer.rename(renamed, "/one/renamed", "/two/moved")

    reader = _reader(repository, navigator, moved)
    assert reader.list_directory("/one") == ()
    assert reader.list_directory("/two") == ("moved",)
    assert reader.read_file("/two/moved") == b"data"


def test_rename_without_replace_rejects_existing_destination(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Rename without replacement rejects an occupied destination name."""
    _, _, writer, base = tree_components
    snapshot = writer.create_file(base, "/source", mode=0o644, uid=0, gid=0)
    snapshot = writer.create_file(snapshot, "/destination", mode=0o644, uid=0, gid=0)

    with pytest.raises(EntryExistsError):
        writer.rename(snapshot, "/source", "/destination")


def test_removing_nonempty_root_is_a_root_operation_error(tree_components: tuple[ObjectRepository, TreeNavigator, TreeWriter, TreeSnapshot]) -> None:
    """Removing the root is rejected as a root operation regardless of its contents."""
    _, _, writer, base = tree_components
    base = writer.create_file(base, "/file", mode=0o644, uid=0, gid=0)

    with pytest.raises(RootOperationError):
        writer.remove_directory(base, "/")
