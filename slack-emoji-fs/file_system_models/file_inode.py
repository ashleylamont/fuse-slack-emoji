from typing import Literal

from file_system_models.inode_object import InodeObject, INODE_TYPE_FILE


class FileInodeObject(InodeObject):
    inode_type: Literal["FILE"] = INODE_TYPE_FILE
    chunks: list[str]  # List of object IDs for data chunks
    size: int