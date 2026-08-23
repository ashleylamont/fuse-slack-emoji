from file_system_models.root_object import RootObject
from object_repository.object_repository import ObjectRepository


class TreeSnapshot:
    """
    A snapshot represents an immutable file tree as resolved from its root object.
    """
    def __init__(self, object_repository: ObjectRepository, root_object_id: str, *, root_object: RootObject | None = None) -> None:
        self._object_repository = object_repository
        _root_object = root_object or self._object_repository.load_root_object(root_object_id)
        self.root_object_id = root_object_id
        self.root_inode_id = _root_object.root_inode_id
        self.parent_root_id = _root_object.parent_root_id
        self.root_object = _root_object