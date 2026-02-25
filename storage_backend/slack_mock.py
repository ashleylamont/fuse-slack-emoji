import datetime
import tempfile
import os
from PIL import Image

import png_encoding

class SlackMockInterface:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(datetime.datetime.now().strftime("slack_mock_%Y%m%d_%H%M%S"))
        self.emoji_paths = {}
        print(f"Initialized SlackMockInterface with temp dir: {self.tmpdir}")

    # Core Slack API methods to mock (we won't muck with aliasing here):
    # - emoji.list (and subsequent image retrieval)
    # - admin.emoji.add
    # - admin.emoji.remove [unused]
    # - admin.emoji.rename [unused]

    def emoji_list(self) -> list[str]:
        # Return a mock list of emojis
        # In our case, we'll do this by listing files in self.tmpdir
        # We'll return a same-shape dictionary as the real Slack API would, and use file:// URLs for the images
        emoji_names = []
        for filename in os.listdir(self.tmpdir):
            self.emoji_paths[filename.split(".")[0]] = os.path.join(self.tmpdir, filename)
            emoji_names.append(filename.split(".")[0])
        return emoji_names

    def admin_emoji_add(self, name: str, image_data: bytes) -> None:
        # Save the image block to a file in self.tmpdir
        image = png_encoding.encode_png_data(image_data)
        image_path = os.path.join(self.tmpdir, f"{name}.png")
        image.save(image_path)

    def emoji_get_payload(self, emoji_name: str) -> bytes:
        # Given an emoji name, read the file and return its contents
        file_path = self.emoji_paths.get(emoji_name)
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"Emoji '{emoji_name}' not found")
        raw_image = Image.open(file_path)
        return png_encoding.decode_png_data(raw_image)


