import stat
from typing import Literal

from file_system_models.object import FileSystemObject, OBJ_TYPE_INODE
from fuse import Stat

INODE_TYPE_FILE: Literal["FILE"] = "FILE"
INODE_TYPE_DIRECTORY: Literal["DIR"] = "DIR"

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

class InodeObject(FileSystemObject):
    object_type: Literal["INO"] = OBJ_TYPE_INODE
    inode_type: Literal["FILE", "DIR"]
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int

    # TODO: move this out of InodeObject into the FUSE layer
    def to_fuse_stat(self, inode_id: str) -> Stat:
        # We're doing all kinds of unspeakable crimes here.
        # This is 100% guaranteed to shoot me in the foot later.
        return Stat(
            st_mode=self.mode | (stat.S_IFREG if self.inode_type==INODE_TYPE_FILE else stat.S_IFDIR),
            # st_ino=stable_ino(inode_id),
            st_nlink=1 if self.inode_type==INODE_TYPE_FILE else 2,
            st_uid=self.uid,
            st_gid=self.gid,
            st_mtime=self.mtime,
            st_ctime=self.ctime,
            st_size=self.size if self.inode_type == INODE_TYPE_FILE else 0
        )