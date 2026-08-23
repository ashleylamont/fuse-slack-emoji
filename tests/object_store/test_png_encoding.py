import struct

import numpy as np
from PIL import Image

from slack_emoji_fs.object_store import png_encoding


def test_png_encoding_round_trips_data_with_opaque_padding() -> None:
    """Encoded objects remain readable while empty padding produces a visible emoji."""
    image = png_encoding.encode_png_data(b"payload")

    alpha = np.array(image)[:, :, 3]

    assert np.count_nonzero(alpha == 255) > alpha.size * 0.99
    assert png_encoding.decode_png_data(image) == b"payload"


def test_png_encoding_still_decodes_the_original_format() -> None:
    """PNGs written before the visible-alpha marker remain readable."""
    payload = b"legacy payload"
    packed_data = struct.pack(
        png_encoding.IMAGE_DATA_PACK_FORMAT,
        len(payload),
        payload,
    )
    image_data = np.frombuffer(packed_data, dtype=np.uint8).reshape((128, 128, 4))
    legacy_image = Image.fromarray(image_data, "RGBA")

    assert png_encoding.decode_png_data(legacy_image) == payload
