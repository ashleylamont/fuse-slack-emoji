from typing import Literal

from slack_emoji_fs.file_system_models.object import FileSystemObject, OBJ_TYPE_INODE

INODE_TYPE_FILE: Literal["FILE"] = "FILE"
INODE_TYPE_DIRECTORY: Literal["DIR"] = "DIR"
type InodeType = Literal["FILE", "DIR"]

INODE_MODE_EXECUTE_OTHER = 0o001
INODE_MODE_WRITE_OTHER = 0o002
INODE_MODE_READ_OTHER = 0o004

INODE_MODE_EXECUTE_GROUP = 0o010
INODE_MODE_WRITE_GROUP = 0o020
INODE_MODE_READ_GROUP = 0o040

INODE_MODE_EXECUTE_OWNER = 0o100
INODE_MODE_WRITE_OWNER = 0o200
INODE_MODE_READ_OWNER = 0o400

INODE_MODE_STICKY = 0o1000
INODE_MODE_SET_GID = 0o2000
INODE_MODE_SET_UID = 0o4000

class InodeObject[TInodeType: InodeType](FileSystemObject[Literal["INO"]]):
    object_type: Literal["INO"] = OBJ_TYPE_INODE
    inode_type: TInodeType
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int
