import struct
import numpy as np
from PIL import Image
from slack_emoji_fs.object_store.errors import ObjectTooLargeError
from slack_emoji_fs.file_system_serialization.format import MAX_OBJECT_SIZE

# Pack image data into binary format
# (Big-endian)
# 1. [uint] Length of image data
# 2. [void*] Image data
IMAGE_DATA_PACK_FORMAT = f">I{MAX_OBJECT_SIZE}s"
VISIBLE_ALPHA_FORMAT_FLAG = 1 << 31

def encode_png_data(data: bytes) -> Image.Image:
    # Encode data into a minimal PNG file
    # Validate size
    if len(data) > MAX_OBJECT_SIZE:
        raise ObjectTooLargeError("Data size exceeds maximum limit of 64KB minus overhead")

    # Pack size and data pointer (using id() as a stand-in for pointer)
    packed_data = struct.pack(
        IMAGE_DATA_PACK_FORMAT,
        len(data) | VISIBLE_ALPHA_FORMAT_FLAG,
        data,
    )

    image_data = np.frombuffer(packed_data, dtype=np.uint8).reshape((128, 128, 4)).copy()
    image_data[:, :, 3] ^= 0xFF
    return Image.fromarray(image_data, "RGBA")

def decode_png_data(png_image: Image.Image) -> bytes:
    # Decode data from a PNG file
    image_data = np.array(png_image.convert("RGBA"))
    packed_data = bytearray(image_data.tobytes())

    encoded_size = struct.unpack(">I", packed_data[:4])[0]
    if encoded_size & VISIBLE_ALPHA_FORMAT_FLAG:
        packed_data[3::4] = bytes(value ^ 0xFF for value in packed_data[3::4])

    # Unpack size and data pointer
    data_size, data_bytes = struct.unpack(IMAGE_DATA_PACK_FORMAT, packed_data)
    data_size &= ~VISIBLE_ALPHA_FORMAT_FLAG
    return data_bytes[:data_size]
