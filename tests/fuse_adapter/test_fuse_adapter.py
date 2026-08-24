from __future__ import annotations

import errno
import os
import stat
from types import SimpleNamespace

import pytest
from fuse import Fuse

from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.fuse_adapter.fuse_adapter import (
    FuseAdapter,
    inode_to_fuse_stat,
    validate_open_flags,
)
from slack_emoji_fs.object_store.errors import ObjectStoreUnavailableError
from slack_emoji_fs.tree_operations.errors import PathNotFoundError


def test_init_forwards_fuse_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passes mount configuration through to the fuse-python base class unchanged."""
    received_args: tuple[object, ...] = ()
    received_kwargs: dict[str, object] = {}

    def record_fuse_init(_self: Fuse, *args: object, **kwargs: object) -> None:
        nonlocal received_args, received_kwargs
        received_args = args
        received_kwargs = kwargs

    monkeypatch.setattr(Fuse, "__init__", record_fuse_init)
    file_system = object.__new__(FileSystem)
    adapter = FuseAdapter(
        file_system,
        version="test-version",
        usage="test-usage",
        dash_s_do="setsingle",
    )

    assert adapter._file_system is file_system
    assert received_args == ()
    assert received_kwargs == {
        "version": "test-version",
        "usage": "test-usage",
        "dash_s_do": "setsingle",
    }


def _adapter(
    file_system: FakeFileSystem,
    *,
    buffer_writes: bool = False,
) -> FuseAdapter:
    """Build an adapter without invoking the native FUSE runtime setup."""
    adapter = object.__new__(FuseAdapter)
    object.__setattr__(adapter, "_file_system", file_system)
    object.__setattr__(adapter, "_buffer_writes", buffer_writes)
    object.__setattr__(adapter, "_write_buffers", {})
    return adapter


def _file(*, mode: int = 0o640, size: int = 23) -> FileInodeObject:
    return FileInodeObject(
        mode=mode,
        uid=1001,
        gid=1002,
        mtime=123,
        ctime=122,
        chunks=[],
        size=size,
    )


def _directory(*, mode: int = 0o750) -> DirectoryInodeObject:
    return DirectoryInodeObject(
        mode=mode,
        uid=1001,
        gid=1002,
        mtime=123,
        ctime=122,
        dirent_object_id="dirent-id",
    )


@pytest.mark.parametrize(
    ("inode", "file_type", "nlink", "size"),
    [
        (_file(), stat.S_IFREG, 1, 23),
        (_directory(), stat.S_IFDIR, 2, 0),
    ],
)
def test_inode_to_fuse_stat_maps_inode_attributes(
    inode: FileInodeObject | DirectoryInodeObject,
    file_type: int,
    nlink: int,
    size: int,
) -> None:
    """Builds a FUSE stat with the correct type, metadata, link count, and size."""
    result = inode_to_fuse_stat(inode)

    assert result.st_mode == file_type | inode.mode
    assert result.st_nlink == nlink
    assert result.st_uid == inode.uid
    assert result.st_gid == inode.gid
    assert result.st_size == size
    assert result.st_mtime == inode.mtime
    assert result.st_ctime == inode.ctime
    assert result.st_atime == inode.mtime


def test_inode_to_fuse_stat_rejects_unknown_inode_type() -> None:
    """Rejects inode objects whose type cannot be represented as a FUSE stat."""
    with pytest.raises(OSError) as raised:
        inode_to_fuse_stat(SimpleNamespace(mode=0o644))

    assert raised.value.errno == errno.EIO


@pytest.mark.parametrize("flags", [-1, 3])
def test_validate_open_flags_rejects_invalid_access_modes(flags: int) -> None:
    """Rejects flag values whose access-mode bits are not read, write, or read-write."""
    with pytest.raises(OSError) as raised:
        validate_open_flags(flags)

    assert raised.value.errno == errno.EINVAL


def test_validate_open_flags_returns_access_mode() -> None:
    """Returns the valid access-mode bits for read-only, write-only, and read-write opens."""
    assert validate_open_flags(os.O_RDONLY) == os.O_RDONLY
    assert validate_open_flags(os.O_WRONLY) == os.O_WRONLY
    assert validate_open_flags(os.O_RDWR) == os.O_RDWR


def test_validate_open_flags_rejects_unsupported_flags() -> None:
    """Rejects platform open flags that the adapter does not support."""
    unsupported = getattr(os, "O_DIRECT", 0) or getattr(os, "O_PATH", 0)
    assert unsupported, "The supported FUSE platform must expose O_DIRECT or O_PATH"

    with pytest.raises(OSError) as raised:
        validate_open_flags(unsupported)

    assert raised.value.errno == errno.EOPNOTSUPP


class FakeFileSystem:
    def __init__(self, inode: object | None = None) -> None:
        self.inode = inode
        self.resolved_paths: list[str] = []
        self.listed_paths: list[str] = []
        self.created: list[tuple[str, dict[str, object]]] = []
        self.read_calls: list[tuple[str, int, int]] = []
        self.read_result = b"read-result"
        self.write_calls: list[tuple[str, bytes, int]] = []
        self.replace_calls: list[tuple[str, bytes]] = []
        self.replace_error: Exception | None = None
        self.truncate_calls: list[tuple[str, int]] = []
        self.directory_creations: list[tuple[str, dict[str, object]]] = []
        self.unlink_calls: list[str] = []
        self.remove_directory_calls: list[str] = []
        self.rename_calls: list[tuple[str, str, bool]] = []

    def resolve(self, path: str) -> SimpleNamespace:
        self.resolved_paths.append(path)
        if isinstance(self.inode, Exception):
            raise self.inode
        return SimpleNamespace(inode_object=self.inode)

    def list_directory(self, path: str) -> tuple[str, ...]:
        self.listed_paths.append(path)
        return ("alpha", "beta")

    def create_file(self, path: str, **kwargs: object) -> None:
        self.created.append((path, kwargs))

    def read_file(self, path: str, *, size: int, offset: int) -> bytes:
        self.read_calls.append((path, size, offset))
        return self.read_result

    def write_file(self, path: str, data: bytes, *, offset: int) -> None:
        self.write_calls.append((path, data, offset))

    def replace_file(self, path: str, contents: bytes) -> None:
        if self.replace_error is not None:
            raise self.replace_error
        self.replace_calls.append((path, contents))

    def truncate_file(self, path: str, length: int) -> None:
        self.truncate_calls.append((path, length))

    def create_directory(self, path: str, **kwargs: object) -> None:
        self.directory_creations.append((path, kwargs))

    def unlink_file(self, path: str) -> None:
        self.unlink_calls.append(path)

    def remove_directory(self, path: str) -> None:
        self.remove_directory_calls.append(path)

    def rename(self, source: str, destination: str, *, replace: bool) -> None:
        self.rename_calls.append((source, destination, replace))


def test_getattr_delegates_resolution_and_converts_stat() -> None:
    """Resolves the requested path and converts its inode into a FUSE stat."""
    file_system = FakeFileSystem(_file())

    result = _adapter(file_system).getattr("/hello")

    assert not isinstance(result, int)
    assert result.st_mode == stat.S_IFREG | 0o640
    assert file_system.resolved_paths == ["/hello"]


def test_getattr_translates_domain_errors_at_callback_boundary() -> None:
    """Translates a path-resolution failure into the corresponding FUSE errno."""
    adapter = _adapter(FakeFileSystem(PathNotFoundError("missing")))

    with pytest.raises(OSError) as raised:
        adapter.getattr("/missing")

    assert raised.value.errno == errno.ENOENT


def test_readdir_includes_dot_entries_and_delegates_path() -> None:
    """Prepends dot entries and delegates directory listing for the requested path."""
    file_system = FakeFileSystem()

    entries = _adapter(file_system).readdir("/docs", offset=37)

    assert tuple(entry.name for entry in entries) == (".", "..", "alpha", "beta")
    assert file_system.listed_paths == ["/docs"]


def test_open_accepts_regular_file_and_does_not_create_a_handle() -> None:
    """Accepts a regular file with valid flags and returns the stateless handle value."""
    file_system = FakeFileSystem(_file())

    assert _adapter(file_system).open("/hello", os.O_RDONLY) == 0
    assert file_system.resolved_paths == ["/hello"]


def test_open_rejects_directory() -> None:
    """Rejects opening a directory through the regular-file open callback."""
    adapter = _adapter(FakeFileSystem(_directory()))

    with pytest.raises(OSError) as raised:
        adapter.open("/docs", os.O_RDONLY)

    assert raised.value.errno == errno.EISDIR


def test_open_rejects_directory_flag_for_regular_file() -> None:
    """Rejects a regular file when the caller explicitly requires a directory."""
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    assert directory_flag, "The supported FUSE platform must expose O_DIRECTORY"
    adapter = _adapter(FakeFileSystem(_file()))

    with pytest.raises(OSError) as raised:
        adapter.open("/hello", os.O_RDONLY | directory_flag)

    assert raised.value.errno == errno.ENOTDIR


def test_create_delegates_context_and_masks_mode() -> None:
    """Passes request identity to file creation and masks the supplied mode."""
    file_system = FakeFileSystem()
    adapter = _adapter(file_system)
    adapter.GetContext = lambda: {"uid": 11, "gid": 22}

    assert adapter.create("/new", os.O_WRONLY, 0o1777) == 0

    assert file_system.created == [
        ("/new", {"mode": 0o1777, "uid": 11, "gid": 22})
    ]


def test_read_delegates_size_and_offset_and_returns_bytes() -> None:
    """Forwards read size and offset and returns the filesystem's byte payload."""
    file_system = FakeFileSystem()

    result = _adapter(file_system).read("/file", 17, 9)

    assert result == b"read-result"
    assert file_system.read_calls == [("/file", 17, 9)]


def test_write_delegates_buffer_and_offset_and_returns_buffer_length() -> None:
    """Forwards the write buffer and offset and reports the number of bytes written."""
    file_system = FakeFileSystem()
    buffer = b"four bytes"

    result = _adapter(file_system).write("/file", buffer, 12)

    assert result == len(buffer)
    assert file_system.write_calls == [("/file", buffer, 12)]


def test_buffered_writes_are_visible_and_publish_once_on_flush() -> None:
    """Combines pending writes locally and publishes the complete file once on flush."""
    file_system = FakeFileSystem(_file(size=0))
    adapter = _adapter(file_system, buffer_writes=True)
    adapter.GetContext = lambda: {"uid": 11, "gid": 22}

    adapter.create("/new", os.O_WRONLY, 0o644)
    adapter.write("/new", b"hello", 0)
    adapter.write("/new", b" world", 5)

    result = adapter.getattr("/new")
    assert not isinstance(result, int)
    assert result.st_size == 11
    assert adapter.read("/new", 20, 0) == b"hello world"
    assert file_system.write_calls == []
    assert file_system.replace_calls == []

    assert adapter.flush("/new") == 0
    assert adapter.flush("/new") == 0
    assert file_system.replace_calls == [("/new", b"hello world")]


def test_buffered_open_loads_existing_contents_and_supports_sparse_writes() -> None:
    """Seeds a write buffer from the file and zero-fills a write beyond its end."""
    file_system = FakeFileSystem(_file(size=3))
    file_system.read_result = b"old"
    adapter = _adapter(file_system, buffer_writes=True)

    adapter.open("/file", os.O_RDWR)
    adapter.write("/file", b"new", 5)
    adapter.release("/file", os.O_RDWR)

    assert file_system.read_calls == [("/file", 3, 0)]
    assert file_system.replace_calls == [("/file", b"old\0\0new")]
    assert "/file" not in adapter._write_buffers


def test_buffered_truncate_changes_pending_contents() -> None:
    """Applies truncation to dirty buffered contents without publishing separately."""
    file_system = FakeFileSystem(_file(size=5))
    file_system.read_result = b"hello"
    adapter = _adapter(file_system, buffer_writes=True)

    adapter.open("/file", os.O_WRONLY)
    adapter.truncate("/file", 2)
    adapter.flush("/file")

    assert file_system.truncate_calls == []
    assert file_system.replace_calls == [("/file", b"he")]


def test_failed_buffered_flush_retains_dirty_contents_for_retry() -> None:
    """Keeps a dirty buffer when publication fails so a later flush can retry it."""
    file_system = FakeFileSystem(_file(size=0))
    adapter = _adapter(file_system, buffer_writes=True)
    adapter.GetContext = lambda: {"uid": 11, "gid": 22}
    adapter.create("/file", os.O_WRONLY, 0o644)
    adapter.write("/file", b"retry me", 0)
    file_system.replace_error = ObjectStoreUnavailableError("Slack unavailable")

    with pytest.raises(OSError) as raised:
        adapter.flush("/file")

    assert raised.value.errno == errno.EIO
    assert adapter._write_buffers["/file"].dirty

    file_system.replace_error = None
    adapter.flush("/file")
    assert file_system.replace_calls == [("/file", b"retry me")]


def test_truncate_delegates_length_and_returns_success() -> None:
    """Forwards the requested file length and returns a successful callback status."""
    file_system = FakeFileSystem()

    result = _adapter(file_system).truncate("/file", 41)

    assert result == 0
    assert file_system.truncate_calls == [("/file", 41)]


def test_mkdir_delegates_masked_mode_and_request_identity() -> None:
    """Passes request identity to directory creation and masks the supplied mode."""
    file_system = FakeFileSystem()
    adapter = _adapter(file_system)
    adapter.GetContext = lambda: {"uid": 11, "gid": 22}

    result = adapter.mkdir("/dir", 0o17777)

    assert result == 0
    assert file_system.directory_creations == [
        ("/dir", {"mode": 0o7777, "uid": 11, "gid": 22})
    ]


def test_unlink_delegates_path_and_returns_success() -> None:
    """Forwards the file path to unlink and returns a successful callback status."""
    file_system = FakeFileSystem()

    result = _adapter(file_system).unlink("/file")

    assert result == 0
    assert file_system.unlink_calls == ["/file"]


def test_rmdir_delegates_path_and_returns_success() -> None:
    """Forwards the directory path to removal and returns a successful callback status."""
    file_system = FakeFileSystem()

    result = _adapter(file_system).rmdir("/dir")

    assert result == 0
    assert file_system.remove_directory_calls == ["/dir"]


def test_rename_requests_replacement_and_returns_success() -> None:
    """Forwards both paths while requesting replacement of an existing destination."""
    file_system = FakeFileSystem()

    result = _adapter(file_system).rename("/old", "/new")

    assert result == 0
    assert file_system.rename_calls == [("/old", "/new", True)]
