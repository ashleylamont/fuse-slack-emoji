"""Typed abstract mixin for the FUSE callbacks implemented by this project."""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from fuse import Direntry, Stat


type FuseStatus = int | None


class FuseOperations(ABC):
    """The pathname-based FUSE operations needed by slack-emoji-fs."""

    @abstractmethod
    def getattr(self, path: str) -> Stat | int:
        """Return attributes for path, or a negative errno."""
        ...

    @abstractmethod
    def readdir(self, path: str, offset: int) -> Iterable[Direntry]:
        """Return the directory's entries, including ``.`` and ``..``."""
        ...

    @abstractmethod
    def open(self, path: str, flags: int) -> FuseStatus:
        """Validate that path can be opened with the supplied OS flags."""
        ...

    @abstractmethod
    def create(
        self,
        path: str,
        flags: int,
        mode: int,
    ) -> FuseStatus:
        """Create and open an empty regular file."""
        ...

    @abstractmethod
    def read(self, path: str, size: int, offset: int) -> bytes | int:
        """Read at most size bytes starting at offset."""
        ...

    @abstractmethod
    def write(self, path: str, buffer: bytes, offset: int) -> int:
        """Write buffer at offset and return its length, or a negative errno."""
        ...

    @abstractmethod
    def truncate(self, path: str, length: int) -> FuseStatus:
        """Resize a regular file to length bytes."""
        ...

    @abstractmethod
    def mkdir(self, path: str, mode: int) -> FuseStatus:
        """Create a directory."""
        ...

    @abstractmethod
    def unlink(self, path: str) -> FuseStatus:
        """Remove a non-directory entry."""
        ...

    @abstractmethod
    def rmdir(self, path: str) -> FuseStatus:
        """Remove an empty directory."""
        ...

    @abstractmethod
    def rename(self, source: str, destination: str) -> FuseStatus:
        """Move or rename an entry."""
        ...

    @abstractmethod
    def chmod(self, path: str, mode: int) -> FuseStatus:
        """Change a path's permission and special mode bits."""
        ...
