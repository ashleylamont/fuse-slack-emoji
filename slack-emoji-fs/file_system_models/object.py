from typing import Literal

from pydantic import BaseModel

OBJ_TYPE_DATA: Literal["DAT"] = "DAT"
OBJ_TYPE_INODE: Literal["INO"] = "INO"
OBJ_TYPE_DIRENT: Literal["DIR"] = "DIR"
OBJ_TYPE_ROOT: Literal["ROT"] = "ROT"

type ObjectType = Literal[
    "DAT",
    "INO",
    "DIR",
    "ROT"
]

class FileSystemObject(BaseModel):
    object_type: ObjectType
