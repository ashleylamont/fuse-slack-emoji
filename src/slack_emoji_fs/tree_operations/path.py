from __future__ import annotations

from slack_emoji_fs.tree_operations.errors import RootOperationError
from slack_emoji_fs.tree_operations.errors import InvalidPathError

class Path:
    def __init__(self, raw_path: str) -> None:
        if not raw_path.startswith("/"):
            raise InvalidPathError("Path must be absolute")
        if "\0" in raw_path:
            raise InvalidPathError("Path must not contain a null byte")
        parts = tuple(part for part in raw_path.split("/") if part)
        if any(part in {".", ".."} for part in parts):
            raise InvalidPathError(
                "Path must not contain '.' or '..' components"
            )
        self.parts = parts
        self.raw_path = "/" + "/".join(parts)
        self.is_root = not parts

    @property
    def name(self) -> str:
        if self.is_root:
            raise RootOperationError("Cannot get name of root")
        return self.parts[-1]

    @property
    def parent_parts(self) -> tuple[str, ...]:
        if self.is_root:
            raise RootOperationError("Cannot get parent parts of root")
        return self.parts[:-1]

    @property
    def parent_path(self) -> Path:
        if self.is_root:
            raise RootOperationError("Cannot get parent path of root")
        return Path("/" + "/".join(self.parent_parts))