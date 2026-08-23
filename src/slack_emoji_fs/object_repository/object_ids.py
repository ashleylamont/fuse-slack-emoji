import time
import uuid
from abc import abstractmethod
from typing import Literal

from slack_emoji_fs.object_repository.errors import InvalidObjectIdError
from pydantic import BaseModel
from slack_emoji_fs.file_system_models.object import ObjectType
from typing_extensions import Protocol, override


class ObjectInfo[TIdVersion: int](BaseModel):
    id_version: TIdVersion
    namespace: str
    object_type: str
    timestamp: float
    unique_id: str


# This probably won't ever get a v2 but I'm implementing this as a standard that I can swap in/out as needed anyways :shrug:
class ObjectIdStandard[TIdVersion: int](Protocol):
    @staticmethod
    @abstractmethod
    def generate_id(object_type: ObjectType, namespace: str) -> str:
        pass

    @staticmethod
    @abstractmethod
    def parse_id(object_id: str) -> ObjectInfo[TIdVersion]:
        pass

    @staticmethod
    @abstractmethod
    def is_valid_id(object_id: str, namespace: str | None) -> bool:
        pass


class ObjectInfoV1(ObjectInfo[Literal[1]]):
    id_version: Literal[1] = 1


class ObjectIdV1Standard(ObjectIdStandard[Literal[1]]):
    @staticmethod
    @override
    def generate_id(object_type: ObjectType, namespace: str | None) -> str:
        return "_".join([
            "efs",
            "v1",
            namespace or "default",
            object_type.lower(),
            str(int(time.time() * 1000)),
            uuid.uuid4().hex,
        ])

    @staticmethod
    @override
    def parse_id(object_id: str) -> ObjectInfoV1:
        [
            efs_prefix,
            version,
            namespace,
            object_type,
            timestamp,
            unique_id
        ] = object_id.split("_")

        if efs_prefix != "efs":
            raise InvalidObjectIdError(f"Object ID '{object_id}' does not appear to be an EFS object")

        if version != "v1":
            raise InvalidObjectIdError(f"Object ID '{object_id}' is not a supported EFS V1 object")

        return ObjectInfoV1(
            namespace=namespace,
            object_type=object_type.upper(),
            timestamp=float(timestamp) / 1000,
            unique_id=unique_id
        )

    @staticmethod
    @override
    def is_valid_id(object_id: str, namespace: str | None) -> bool:
        # This isn't a 100% accurate check, but it's a quick and dirty screen for obviously incorrect IDs
        return object_id.startswith(f"efs_v1_{namespace or "default"}")
