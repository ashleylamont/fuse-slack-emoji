import struct
import numpy as np
from PIL import Image
from file_system_serialization.format import MAX_OBJECT_SIZE

# Pack image data into binary format
# (Big-endian)
# 1. [uint] Length of image data
# 2. [void*] Image data
IMAGE_DATA_PACK_FORMAT = f">I{MAX_OBJECT_SIZE}s"

def encode_png_data(data: bytes) -> Image.Image:
    # Encode data into a minimal PNG file
    # Validate size
    if len(data) > MAX_OBJECT_SIZE:
        raise ValueError("Data size exceeds maximum limit of 64KB minus overhead")

    # Pack size and data pointer (using id() as a stand-in for pointer)
    packed_data = struct.pack(IMAGE_DATA_PACK_FORMAT, len(data), data)

    # Ok now let's stuff it into an ndarray and make that a PNG file
    image_data = np.zeros((128, 128, 4), dtype=np.uint8)
    for x in range(128):
        for y in range(128):
            for channel in range(4):
                index = (x * 128 + y) * 4 + channel
                image_data[x, y, channel] = packed_data[index] or 0
    return Image.fromarray(image_data, 'RGBA')

def decode_png_data(png_image: Image.Image) -> bytes:
    # Decode data from a PNG file
    image_data = np.array(png_image)
    packed_data = bytearray()
    for x in range(128):
        for y in range(128):
            for channel in range(4):
                packed_data.append(image_data[x, y, channel])
    # Unpack size and data pointer
    data_size, data_bytes = struct.unpack(IMAGE_DATA_PACK_FORMAT, packed_data)
    return data_bytes[:data_size]
