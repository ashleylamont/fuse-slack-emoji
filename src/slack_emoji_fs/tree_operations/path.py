from __future__ import annotations

# We're not handling relative paths or special components like '.' or '..' for simplicity (could be added later)
class Path:
    def __init__(self, path: str) -> None:
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        self.raw_path = path
        self.parts = tuple(
            part for part in path.split("/") if part
        )
        self.is_root = len(self.parts) == 0
        self.name = self.parts[-1] if not self.is_root else None
        self.parent_parts = self.parts[:-1]

    @property
    def parent_path(self) -> Path | None:
        if self.is_root:
            return None
        return Path("/" + "/".join(self.parent_parts))