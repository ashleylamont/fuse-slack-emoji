from __future__ import annotations

from typing import Callable

from slack_emoji_fs.file_system_models.object import ObjectType
from slack_emoji_fs.object_repository.object_ids import ObjectInfoV1, ObjectIdV1Standard
from slack_emoji_fs.object_store.object_store import ObjectStore
from typing_extensions import TypeVar


class ObjectStoreAccessor:
    def __init__(self, object_store: ObjectStore, namespace: str) -> None:
        self.object_store = object_store
        self.namespace = namespace

    def query(self) -> ObjectStoreAccessorQuery:
        return ObjectStoreAccessorQuery(self)

SortKey = TypeVar("SortKey", float, str)

class ObjectStoreAccessorQuery:
    def __init__(self, object_store_accessor: ObjectStoreAccessor) -> None:
        self.object_store_accessor = object_store_accessor
        # This could be moved to something that doesn't rely on a ton of intermediate arrays down the line
        # But we're fetching the whole list of IDs no matter what each time, so it's kinda moot for now
        self.query_results: list[tuple[str, ObjectInfoV1]] = [
            (object_id, ObjectIdV1Standard.parse_id(object_id))
                for object_id in self.object_store_accessor.object_store.list_ids()
                if ObjectIdV1Standard.is_valid_id(object_id, self.object_store_accessor.namespace)
        ]

    def _filter_results(self, filter_fn: Callable[[ObjectInfoV1], bool]) -> ObjectStoreAccessorQuery:
        self.query_results = [
            (object_id, object_info)
                for (object_id, object_info) in self.query_results
                if filter_fn(object_info)
        ]
        return self

    def _sort_results[SortKey](self, key: Callable[[ObjectInfoV1], SortKey], reverse: bool = False) -> ObjectStoreAccessorQuery:
        pair_key: Callable[[tuple[str, ObjectInfoV1]], SortKey] = lambda pair: key(pair[1])
        self.query_results = sorted(self.query_results, key=pair_key, reverse=reverse)
        return self

    def with_object_type(self, object_type: ObjectType) -> ObjectStoreAccessorQuery:
        return self._filter_results(lambda object_info: object_info.object_type == object_type)

    def sort_by_timestamp(self, descending: bool = True) -> ObjectStoreAccessorQuery:
        return self._sort_results(lambda object_info: object_info.timestamp, descending)

    def object_ids(self) -> list[str]:
        return [object_id for (object_id, _object_info) in self.query_results]

    def first_object_id(self) -> str | None:
        return self.query_results[0][0] if len(self.query_results) > 0 else None

    def object_infos(self) -> list[ObjectInfoV1]:
        return [object_info for (_object_id, object_info) in self.query_results]

    def first_object_info(self) -> ObjectInfoV1 | None:
        return self.query_results[0][1] if len(self.query_results) > 0 else None

    def object_entries(self) -> list[tuple[str, ObjectInfoV1]]:
        return self.query_results

    def first_object_entry(self) -> tuple[str, ObjectInfoV1] | None:
        return self.query_results[0] if len(self.query_results) > 0 else None