import struct

import cbor2
from slack_emoji_fs.object_repository.errors import CorruptObjectError, WrongObjectTypeError
from slack_emoji_fs.object_store.errors import ObjectTooLargeError
from slack_emoji_fs.file_system_models.data_chunk_object import DataChunkObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.inode_object import INODE_TYPE_DIRECTORY, INODE_TYPE_FILE
from slack_emoji_fs.file_system_models.object import OBJ_TYPE_DATA, OBJ_TYPE_ROOT, \
    OBJ_TYPE_DIRENT, OBJ_TYPE_INODE
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.format import OBJ_MAX_PAYLOAD_SIZE, OBJ_DATA_PACK_FORMAT, OBJ_MAGIC_BYTES


def encode_fs_object(
        fs_object: DataChunkObject | RootObject | FileInodeObject | DirectoryInodeObject | DirectoryEntryObject
) -> bytes:
    object_type = fs_object.object_type
    data = fs_object.model_dump(exclude={"object_type"})
    payload_data = cbor2.dumps(data)
    if len(payload_data) > OBJ_MAX_PAYLOAD_SIZE:
        raise ObjectTooLargeError("Payload size exceeds maximum limit")
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

def decode_fs_object(encoded_data: bytes) -> DataChunkObject | RootObject | FileInodeObject | DirectoryInodeObject | DirectoryEntryObject:
    try:
        unpacked_data = struct.unpack(OBJ_DATA_PACK_FORMAT, encoded_data)
    except struct.error as error:
        raise CorruptObjectError("Object record has an invalid length") from error
    magic_bytes, object_type, payload_size, checksum, payload_data = unpacked_data
    if magic_bytes != OBJ_MAGIC_BYTES.encode("utf-8"):
        raise CorruptObjectError("Invalid magic bytes")
    actual_payload = payload_data[:payload_size]
    actual_checksum = sum(actual_payload) % (2 ** 32)
    if actual_checksum != checksum:
        raise CorruptObjectError("Checksum mismatch")
    data = cbor2.loads(actual_payload)
    object_type = object_type.decode("utf-8").upper()
    if object_type == OBJ_TYPE_DATA:
        return DataChunkObject(object_type=OBJ_TYPE_DATA, data=data["data"])
    elif object_type == OBJ_TYPE_INODE:
        inode_type = data.get("inode_type")
        if inode_type == INODE_TYPE_FILE:
            return FileInodeObject(object_type=OBJ_TYPE_INODE, **data)
        elif inode_type == INODE_TYPE_DIRECTORY:
            return DirectoryInodeObject(object_type=OBJ_TYPE_INODE, **data)
        else:
            raise CorruptObjectError(f"Unknown inode type: {inode_type}")
    elif object_type == OBJ_TYPE_DIRENT:
        return DirectoryEntryObject(object_type=OBJ_TYPE_DIRENT, **data)
    elif object_type == OBJ_TYPE_ROOT:
        return RootObject(object_type=OBJ_TYPE_ROOT, **data)
    else:
        raise NotImplementedError(f"Object type {object_type} not implemented")

def decode_root_object(encoded_data: bytes) -> RootObject:
    decoded_object = decode_fs_object(encoded_data)
    if not isinstance(decoded_object, RootObject):
        raise WrongObjectTypeError(f"Attempted to decode non-root object as root object")
    return decoded_object

def decode_dirent_object(encoded_data: bytes) -> DirectoryEntryObject:
    decoded_object = decode_fs_object(encoded_data)
    if not isinstance(decoded_object, DirectoryEntryObject):
        raise WrongObjectTypeError(f"Attempted to decode non-directory-entry object as directory-entry object")
    return decoded_object

def decode_directory_entry_object(encoded_data: bytes) -> DirectoryEntryObject:
    return decode_dirent_object(encoded_data)

def decode_inode_object(encoded_data: bytes) -> FileInodeObject | DirectoryInodeObject:
    decoded_object = decode_fs_object(encoded_data)
    if not isinstance(decoded_object, (FileInodeObject, DirectoryInodeObject)):
        raise WrongObjectTypeError(f"Attempted to decode non-inode object as inode object")
    return decoded_object

def decode_data_chunk_object(encoded_data: bytes) -> DataChunkObject:
    decoded_object = decode_fs_object(encoded_data)
    if not isinstance(decoded_object, DataChunkObject):
        raise WrongObjectTypeError(f"Attempted to decode non-data-chunk object as data chunk object")
    return decoded_object
