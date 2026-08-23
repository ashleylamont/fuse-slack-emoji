KB = 1024
MAX_OBJECT_SIZE = 64 * KB - 4  # 64KB minus some overhead for the header so that we can have nice 128x128 emojis

OBJ_MAGIC_BYTES = "EFS"

OBJ_HEADER_SIZE = 3 + 3 + 4 + 4  # Magic bytes + type + payload size + checksum
OBJ_MAX_PAYLOAD_SIZE = MAX_OBJECT_SIZE - OBJ_HEADER_SIZE

# Pack object data into binary format
# (Big-endian)
# 1. [3 bytes] Magic bytes "EFS"
# 2. [3 bytes] Object type
# 3. [uint] Payload size
# 4. [uint] Checksum (simple sum of payload bytes modulo 2^32)
# 5. [void*] Payload data
OBJ_DATA_PACK_FORMAT = f">3s3sII{OBJ_MAX_PAYLOAD_SIZE}s"

MAX_DATA_CHUNK_PAYLOAD_SIZE = OBJ_MAX_PAYLOAD_SIZE - 100  # Leave some margin for overhead (just kinda guessing here)