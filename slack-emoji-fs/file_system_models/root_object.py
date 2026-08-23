from typing import Literal

from file_system_models.object import FileSystemObject, OBJ_TYPE_ROOT


class RootObject(FileSystemObject):
    object_type: Literal["ROT"] = OBJ_TYPE_ROOT
    parent_root_id: str | None  # Object ID of the parent root (empty for the initial root)
    root_inode_id: str  # Object ID of the root inode