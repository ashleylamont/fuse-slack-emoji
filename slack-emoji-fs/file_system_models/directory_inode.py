from typing import Literal

from file_system_models.inode_object import INODE_TYPE_DIRECTORY, InodeObject


class DirectoryInodeObject(InodeObject):
    inode_type: Literal["DIR"] = INODE_TYPE_DIRECTORY
    dirent_object_id: str  # Object ID for the directory entry object