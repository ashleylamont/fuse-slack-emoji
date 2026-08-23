from typing import List

from typing_extensions import override

from slack_emoji_fs.object_store.object_store import ObjectStore


class MemoryObjectStore(ObjectStore):
    def __init__(self):
        # Just store objects in an in-memory dict for simplicity
        self.object_store = {}

    @override
    def list_ids(self) -> List[str]:
        return list(self.object_store.keys())

    @override
    def put(self, object_id: str, object_data: bytes) -> None:
        if object_id in self.object_store:
            raise Exception(f"Object with id {object_id} already exists")
        self.object_store[object_id] = object_data

    @override
    def get(self, object_id: str) -> bytes | None:
        return self.object_store.get(object_id)
