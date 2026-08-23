import datetime
import tempfile
import os
from PIL import Image

from slack_emoji_fs.object_store import png_encoding
from slack_emoji_fs.object_store.object_store import ObjectStore
from typing_extensions import override


class LocalFileObjectStore(ObjectStore):
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(datetime.datetime.now().strftime("slack_mock_%Y%m%d_%H%M%S"))
        print(f"Initialized SlackMockInterface with temp dir: {self.tmpdir}")

    @override
    def list_ids(self) -> list[str]:
        return [
            file_name.split(".")[0] for file_name in os.listdir(self.tmpdir)
        ]

    @override
    def put(self, object_id: str, object_data: bytes) -> None:
        # Assert that an object at this ID does not already exist
        image_path = os.path.join(self.tmpdir, f"{object_id}.png")
        if os.path.exists(image_path):
            raise Exception(f"Object already exists with id {object_id}")
        image = png_encoding.encode_png_data(object_data)
        image.save(image_path)

    @override
    def get(self, object_id: str) -> bytes | None:
        image_path = os.path.join(self.tmpdir, f"{object_id}.png")
        if not os.path.exists(image_path):
            return None
        image = Image.open(image_path)
        return png_encoding.decode_png_data(image)


