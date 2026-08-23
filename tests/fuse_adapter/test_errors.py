import errno

import pytest

from slack_emoji_fs.fuse_adapter.errors import (
    err_to_fuse_errno,
    translate_fuse_errors,
)
from slack_emoji_fs.object_repository.errors import (
    CorruptObjectError,
    InvalidNamespaceError,
    InvalidObjectIdError,
    ObjectNotFoundError,
    WrongObjectTypeError,
)
from slack_emoji_fs.object_store.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreUnavailableError,
    ObjectTooLargeError,
)
from slack_emoji_fs.tree_operations.errors import (
    CorruptTreeError,
    DirectoryNotEmptyError,
    EntryExistsError,
    InvalidFileRangeError,
    InvalidPathError,
    IsDirectoryError,
    NotDirectoryError,
    PathNotFoundError,
    RootOperationError,
)


@pytest.mark.parametrize(
    ("exception", "expected_errno"),
    [
        (PathNotFoundError(), errno.ENOENT),
        (NotDirectoryError(), errno.ENOTDIR),
        (IsDirectoryError(), errno.EISDIR),
        (EntryExistsError(), errno.EEXIST),
        (DirectoryNotEmptyError(), errno.ENOTEMPTY),
        (InvalidPathError(), errno.EINVAL),
        (InvalidFileRangeError(), errno.EINVAL),
        (RootOperationError(), errno.EINVAL),
        (CorruptTreeError(), errno.EIO),
        (InvalidNamespaceError(), errno.EIO),
        (InvalidObjectIdError(), errno.EIO),
        (ObjectNotFoundError(), errno.EIO),
        (CorruptObjectError(), errno.EIO),
        (WrongObjectTypeError(), errno.EIO),
        (ObjectAlreadyExistsError(), errno.EIO),
        (ObjectStoreUnavailableError(), errno.EIO),
        (ObjectTooLargeError(), errno.EFBIG),
    ],
)
def test_expected_exception_mapping(
    exception: Exception,
    expected_errno: int,
) -> None:
    """Maps each domain exception to its documented FUSE errno."""
    assert err_to_fuse_errno(exception) == expected_errno


def test_mapper_rejects_an_unexpected_exception() -> None:
    """Rejects exceptions without an explicit domain-to-errno mapping."""
    with pytest.raises(TypeError, match="No FUSE errno mapping"):
        err_to_fuse_errno(ValueError("not a domain error"))


def test_boundary_raises_os_error_with_mapped_errno() -> None:
    """Converts a mapped callback failure into OSError while preserving its message."""
    @translate_fuse_errors()
    def callback() -> None:
        raise PathNotFoundError("missing")

    with pytest.raises(OSError) as raised:
        callback()

    assert raised.value.errno == errno.ENOENT
    assert str(raised.value).endswith("missing")


def test_boundary_can_override_root_operation_errno() -> None:
    """Uses the configured busy errno when translating root-operation failures."""
    @translate_fuse_errors(root_operation_errno=errno.EBUSY)
    def callback() -> None:
        raise RootOperationError("cannot operate on root")

    with pytest.raises(OSError) as raised:
        callback()

    assert raised.value.errno == errno.EBUSY


@pytest.mark.parametrize(
    "exception",
    [
        TypeError("programming error"),
        AttributeError("programming error"),
        OSError(errno.EPERM, "already translated"),
    ],
)
def test_boundary_does_not_translate_unexpected_exceptions(
    exception: Exception,
) -> None:
    """Leaves programming and already-translated errors unchanged at the boundary."""
    @translate_fuse_errors()
    def callback() -> None:
        raise exception

    with pytest.raises(type(exception)) as raised:
        callback()

    assert raised.value is exception
