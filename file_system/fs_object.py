import hashlib
import stat
import struct
import time
import uuid
from typing import Union, Literal

import cbor2
from fuse import Stat
from pydantic import BaseModel

from storage_backend.png_encoding import MAX_EMOJI_SIZE

OBJ_TYPE_DATA: Literal["DAT"] = "DAT"
OBJ_TYPE_INODE: Literal["INO"] = "INO"
OBJ_TYPE_DIRECTORY: Literal["DIR"] = "DIR"
OBJ_TYPE_ROOT: Literal["ROT"] = "ROT"

type ObjectType = Literal[
    "DAT",
    "INO",
    "DIR",
    "ROT"
]

OBJ_MAGIC_BYTES = "EFS"

OBJ_HEADER_SIZE = 3 + 3 + 4 + 4  # Magic bytes + type + payload size + checksum
OBJ_MAX_PAYLOAD_SIZE = MAX_EMOJI_SIZE - OBJ_HEADER_SIZE

# Pack object data into binary format
# (Big-endian)
# 1. [3 bytes] Magic bytes "EFS"
# 2. [3 bytes] Object type
# 3. [uint] Payload size
# 4. [uint] Checksum (simple sum of payload bytes modulo 2^32)
# 5. [void*] Payload data
OBJ_DATA_PACK_FORMAT = f">3s3sII{OBJ_MAX_PAYLOAD_SIZE}s"


class FileSystemObject(BaseModel):
    object_type: ObjectType


MAX_DATA_CHUNK_PAYLOAD_SIZE = OBJ_MAX_PAYLOAD_SIZE - 100  # Leave some margin for overhead (just kinda guessing here)


class ObjectDataChunk(FileSystemObject):
    object_type: Literal["DAT"] = OBJ_TYPE_DATA
    data: bytes


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
    inode_type: Union[INODE_TYPE_FILE, INODE_TYPE_DIRECTORY]
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int


class FileInodeObject(InodeObject):
    inode_type: Literal["FILE"] = INODE_TYPE_FILE
    chunks: list[str]  # List of object IDs for data chunks
    size: int


class DirectoryInodeObject(InodeObject):
    inode_type: Literal["DIR"] = INODE_TYPE_DIRECTORY
    dir_object_id: str  # Object ID for the directory object

def stable_ino(inode_id: str) -> int:
    # 64-bit positive integer, non-zero
    h = hashlib.sha256(inode_id.encode("utf-8")).digest()
    ino = int.from_bytes(h[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF
    return ino or 1

def inode_to_fuse_stat(inode: InodeObject, inode_id: str) -> Stat:
    return Stat(
        st_mode=inode.mode | (stat.S_IFREG if inode.inode_type==INODE_TYPE_FILE else stat.S_IFDIR),
        st_ino=stable_ino(inode_id),
        st_nlink=1 if inode.inode_type==INODE_TYPE_FILE else 2,
        st_uid=inode.uid,
        st_gid=inode.gid,
        st_mtime=inode.mtime,
        st_ctime=inode.ctime,
        st_size=inode.size if isinstance(inode, FileInodeObject) else 0
    )


class DirectoryEntryObject(FileSystemObject):
    object_type: Literal["DIR"] = OBJ_TYPE_DIRECTORY
    entries: dict[str, str]  # Mapping from filename to object ID


class RootObject(FileSystemObject):
    object_type: Literal["ROT"] = OBJ_TYPE_ROOT
    parent_root_id: str | None  # Object ID of the parent root (empty for the initial root)
    root_inode_id: str  # Object ID of the root inode


def encode_fs_object(fs_object: FileSystemObject) -> bytes:
    object_type = fs_object.object_type
    data = fs_object.model_dump(exclude={"object_type"})
    payload_data = cbor2.dumps(data)
    if len(payload_data) > OBJ_MAX_PAYLOAD_SIZE:
        raise ValueError("Payload size exceeds maximum limit")
    checksum = sum(payload_data) % (2 ** 32)
    packed_data = struct.pack(
        OBJ_DATA_PACK_FORMAT,
        OBJ_MAGIC_BYTES.encode("utf-8"),
        object_type.encode('utf-8'),
        len(payload_data),
        checksum,
        payload_data.ljust(OBJ_MAX_PAYLOAD_SIZE, b'\0')
    )
    return packed_data


def decode_fs_object(encoded_data: bytes) -> FileSystemObject:
    unpacked_data = struct.unpack(OBJ_DATA_PACK_FORMAT, encoded_data)
    magic_bytes, object_type, payload_size, checksum, payload_data = unpacked_data
    if magic_bytes != OBJ_MAGIC_BYTES.encode("utf-8"):
        raise ValueError("Invalid magic bytes")
    actual_payload = payload_data[:payload_size]
    actual_checksum = sum(actual_payload) % (2 ** 32)
    if actual_checksum != checksum:
        raise ValueError("Checksum mismatch")
    data = cbor2.loads(actual_payload)
    object_type = object_type.decode("utf-8").upper()
    if object_type == OBJ_TYPE_DATA:
        return ObjectDataChunk(object_type=OBJ_TYPE_DATA, data=data)
    elif object_type == OBJ_TYPE_INODE:
        inode_type = data.get("inode_type")
        if inode_type == INODE_TYPE_FILE:
            return FileInodeObject(object_type=OBJ_TYPE_INODE, **data)
        elif inode_type == INODE_TYPE_DIRECTORY:
            return DirectoryInodeObject(object_type=OBJ_TYPE_INODE, **data)
        else:
            raise ValueError(f"Unknown inode type: {inode_type}")
    elif object_type == OBJ_TYPE_DIRECTORY:
        return DirectoryEntryObject(object_type=OBJ_TYPE_DIRECTORY, **data)
    elif object_type == OBJ_TYPE_ROOT:
        return RootObject(object_type=OBJ_TYPE_ROOT, **data)
    else:
        raise NotImplementedError(f"Object type {object_type} not implemented")


def generate_object_id(object_type: ObjectType) -> str:
    # If this is a root object, then we want to return a fixed-format ID that is chronologically sortable
    # For all other objects (and root suffixes), we can use a random UUID4
    prefix = "efs_" + object_type.lower() + "_"
    if object_type == OBJ_TYPE_ROOT:
        timestamp = int(time.time() * 1000)
        prefix += f"{timestamp:016x}_"
    unique_id = uuid.uuid4().hex
    return prefix + unique_id
