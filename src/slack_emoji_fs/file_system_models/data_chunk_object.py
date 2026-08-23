from typing import Literal

from slack_emoji_fs.file_system_models.object import FileSystemObject, OBJ_TYPE_DATA


class DataChunkObject(FileSystemObject):
    object_type: Literal["DAT"] = OBJ_TYPE_DATA
    data: bytes