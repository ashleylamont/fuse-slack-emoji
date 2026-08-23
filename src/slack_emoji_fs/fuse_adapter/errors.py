from collections.abc import Callable
from errno import (
    EEXIST,
    EFBIG,
    EINVAL,
    EIO,
    EISDIR,
    ENOENT,
    ENOTDIR,
    ENOTEMPTY,
)
from functools import wraps
from typing import ParamSpec, TypeVar

from slack_emoji_fs.object_repository.errors import (
    ObjectRepositoryError,
)
from slack_emoji_fs.object_store.errors import (
    ObjectStoreError,
    ObjectTooLargeError,
)
from slack_emoji_fs.tree_operations.errors import (
    CorruptTreeError,
    DirectoryNotEmptyError,
    EntryExistsError,
    FileSystemError,
    InvalidFileRangeError,
    InvalidPathError,
    IsDirectoryError,
    NotDirectoryError,
    PathNotFoundError,
    RootOperationError,
)


def err_to_fuse_errno(exception: Exception) -> int:
    """Map an expected domain-layer exception to a positive errno value."""
    match exception:
        case PathNotFoundError():
            return ENOENT
        case NotDirectoryError():
            return ENOTDIR
        case IsDirectoryError():
            return EISDIR
        case EntryExistsError():
            return EEXIST
        case DirectoryNotEmptyError():
            return ENOTEMPTY
        case InvalidPathError() | InvalidFileRangeError() | RootOperationError():
            return EINVAL
        case CorruptTreeError() | ObjectRepositoryError():
            return EIO
        case ObjectTooLargeError():
            return EFBIG
        case ObjectStoreError():
            # Store-level duplicate and availability failures do not describe a
            # conflicting directory entry. They indicate that persistence failed.
            return EIO
        case FileSystemError():
            # New domain errors fail safely until they receive a more specific map.
            return EIO
        case _:
            raise TypeError(
                f"No FUSE errno mapping for {type(exception).__name__}"
            )


_P = ParamSpec("_P")
_R = TypeVar("_R")


def translate_fuse_errors(
    *,
    root_operation_errno: int = EINVAL,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Translate declared domain failures at a FUSE callback boundary.

    Other exceptions, including programming errors and an existing ``OSError``,
    deliberately pass through unchanged.
    """

    def decorator(callback: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(callback)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                return callback(*args, **kwargs)
            except RootOperationError as exception:
                raise OSError(root_operation_errno, str(exception)) from exception
            except (
                FileSystemError,
                ObjectRepositoryError,
                ObjectStoreError,
            ) as exception:
                raise OSError(
                    err_to_fuse_errno(exception),
                    str(exception),
                ) from exception

        return wrapped

    return decorator


__all__ = [
    "err_to_fuse_errno",
    "translate_fuse_errors",
]
