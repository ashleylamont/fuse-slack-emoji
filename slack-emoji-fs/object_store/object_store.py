from typing import List, Protocol
from abc import abstractmethod


class ObjectStore(Protocol):
    """
    Object Store defines a protocol for id-addressable object storage, with limited interfaces for updating objects.
    These limitations are informed by the constraints imposed by assuming compatibility with Slack's emoji API.
    """
    @abstractmethod
    def list_ids(self) -> List[str]:
        pass

    @abstractmethod
    def put(self, object_id: str, object_data: bytes) -> None:
        pass

    @abstractmethod
    def get(self, object_id: str) -> bytes | None:
        pass