import struct
from typing import TypedDict

import pytest

from slack_emoji_fs.file_system_models.data_chunk_object import DataChunkObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.codec import (
    decode_data_chunk_object,
    decode_fs_object,
    decode_root_object,
    encode_fs_object,
)
from slack_emoji_fs.file_system_serialization.format import OBJ_DATA_PACK_FORMAT, OBJ_MAX_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.errors import CorruptObjectError, WrongObjectTypeError
from slack_emoji_fs.object_store.errors import ObjectTooLargeError


type FileSystemObjectModel = (
    DataChunkObject
    | DirectoryEntryObject
    | DirectoryInodeObject
    | FileInodeObject
    | RootObject
)


class _InodeMetadata(TypedDict):
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int


def _inode_metadata() -> _InodeMetadata:
    return {"mode": 0o644, "uid": 1000, "gid": 1000, "mtime": 1, "ctime": 2}


@pytest.mark.parametrize(
    "fs_object",
    [
        DataChunkObject(data=b"hello"),
        DirectoryEntryObject(entries={"child": "efs_v1_test_ino_1_child"}),
        FileInodeObject(chunks=["efs_v1_test_dat_1_chunk"], size=5, **_inode_metadata()),
        DirectoryInodeObject(dirent_object_id="efs_v1_test_dir_1_entries", **_inode_metadata()),
        RootObject(parent_root_id=None, root_inode_id="efs_v1_test_ino_1_root"),
    ],
)
def test_codec_round_trips_every_filesystem_object_type(fs_object: FileSystemObjectModel) -> None:
    """Each supported filesystem model survives encoding and decoding unchanged."""
    assert decode_fs_object(encode_fs_object(fs_object)) == fs_object


def test_codec_rejects_bad_magic_bytes() -> None:
    """Records with an invalid format marker are reported as corrupt."""
    encoded = bytearray(encode_fs_object(DataChunkObject(data=b"hello")))
    encoded[:3] = b"BAD"

    with pytest.raises(CorruptObjectError, match="magic"):
        decode_fs_object(bytes(encoded))


def test_codec_rejects_checksum_mismatch() -> None:
    """Payload tampering is detected through checksum validation."""
    encoded = bytearray(encode_fs_object(DataChunkObject(data=b"hello")))
    encoded[10] ^= 1  # The payload starts immediately after the 3s, 3s, uint, uint header.

    with pytest.raises(CorruptObjectError, match="Checksum"):
        decode_fs_object(bytes(encoded))


def test_typed_decoder_rejects_a_valid_object_of_the_wrong_type() -> None:
    """A valid record of another model type is rejected by a typed decoder."""
    with pytest.raises(WrongObjectTypeError, match="non-root"):
        decode_root_object(encode_fs_object(DataChunkObject(data=b"hello")))


def test_encoding_rejects_payloads_larger_than_the_object_limit() -> None:
    """Encoding refuses payloads that exceed the filesystem object limit."""
    with pytest.raises(ObjectTooLargeError):
        encode_fs_object(DataChunkObject(data=b"x" * OBJ_MAX_PAYLOAD_SIZE))


def test_codec_normalizes_truncated_records_to_corrupt_object_errors() -> None:
    """Incomplete serialized records produce the codec's corruption error."""
    with pytest.raises(CorruptObjectError):
        decode_fs_object(struct.pack(">3s", b"EFS"))
