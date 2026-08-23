from typing import Literal

from slack_emoji_fs.file_system_models.object import OBJ_TYPE_DIRENT, FileSystemObject


class DirectoryEntryObject(FileSystemObject[Literal["DIR"]]):
    object_type: Literal["DIR"] = OBJ_TYPE_DIRENT
    entries: dict[str, str]  # Mapping from filename to object ID
