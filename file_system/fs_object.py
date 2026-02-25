from storage_backend.png_encoding import MAX_EMOJI_SIZE
import json
import struct

OBJ_TYPE_DATA = b"DAT"
OBJ_TYPE_INODE = b"INO"
OBJ_TYPE_DIRECTORY = b"DIR"
OBJ_TYPE_ROOT = b"ROT"

OBJ_MAGIC_BYTES = b"EFS"

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


def encode_fs_object(object_type: bytes, data: dict) -> bytes:
    payload_data = json.dumps(data).encode('utf-8')
    if len(payload_data) > OBJ_MAX_PAYLOAD_SIZE:
        raise ValueError("Payload size exceeds maximum limit")
    checksum = sum(payload_data) % (2**32)
    packed_data = struct.pack(
        OBJ_MAGIC_BYTES,
        object_type,
        len(payload_data),
        checksum,
        payload_data.ljust(OBJ_MAX_PAYLOAD_SIZE, b'\0')
    )
    return packed_data

def decode_fs_object(encoded_data: bytes) -> tuple[bytes, dict]:
    unpacked_data = struct.unpack(OBJ_DATA_PACK_FORMAT, encoded_data)
    magic_bytes, object_type, payload_size, checksum, payload_data = unpacked_data
    if magic_bytes != OBJ_MAGIC_BYTES:
        raise ValueError("Invalid magic bytes")
    actual_payload = payload_data[:payload_size]
    actual_checksum = sum(actual_payload) % (2**32)
    if actual_checksum != checksum:
        raise ValueError("Checksum mismatch")
    data = json.loads(actual_payload.decode('utf-8'))
    return object_type, data
