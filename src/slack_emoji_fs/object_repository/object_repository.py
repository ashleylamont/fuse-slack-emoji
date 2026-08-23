from slack_emoji_fs.file_system_models.data_chunk_object import DataChunkObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.object import FileSystemObject, OBJ_TYPE_DATA
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.codec import decode_root_object, decode_inode_object, \
    decode_dirent_object, decode_data_chunk_object, encode_fs_object
from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.object_ids import ObjectIdV1Standard
from slack_emoji_fs.object_repository.object_store_accessor import ObjectStoreAccessor
from slack_emoji_fs.object_store.object_store import ObjectStore


class ObjectRepository:
    def __init__(self, object_store: ObjectStore, namespace: str) -> None:
        self.object_store = object_store
        self.namespace = namespace
        if not namespace.isalpha():
            raise Exception(f"Namespace {namespace} is not a valid namespace")
        self.object_store_accessor = ObjectStoreAccessor(self.object_store, self.namespace)

    def _load_object_payload(self, object_id: str) -> bytes:
        """Get an object from the object store given its object ID."""
        payload = self.object_store.get(object_id)
        if payload is None:
            raise Exception(f"Object with ID {object_id} does not exist")
        return payload

    def load_root_object(self, root_object_id: str) -> RootObject:
        """Load a root object from the object store given its object ID."""
        return decode_root_object(self._load_object_payload(root_object_id))

    # def load_latest_root_object(self) -> RootObject | None:
    #     """Load the latest root object from the object store."""
    #     latest_root_object_id = (self.object_store_accessor.query()
    #                              .with_object_type(OBJ_TYPE_ROOT)
    #                              .sort_by_timestamp()
    #                              .first_object_id())
    #     if latest_root_object_id is None:
    #         return None
    #     return self.load_root_object(latest_root_object_id)

    def load_inode_object(self, inode_object_id: str) -> FileInodeObject | DirectoryInodeObject:
        """Load an inode object from the object store given its object ID."""
        return decode_inode_object(self._load_object_payload(inode_object_id))

    def load_dirent_object(self, dirent_object_id: str) -> DirectoryEntryObject:
        """Load a directory entry object from the object store given its object ID."""
        return decode_dirent_object(self._load_object_payload(dirent_object_id))

    def load_data_chunk_object(self, data_chunk_object_id: str) -> DataChunkObject:
        """Load a data chunk object from the object store given its object ID."""
        return decode_data_chunk_object(self._load_object_payload(data_chunk_object_id))

    def store_fs_object(self, fs_object: FileSystemObject) -> str:
        """Store a file system object in the object store and return its new object ID."""
        object_id = ObjectIdV1Standard.generate_id(fs_object.object_type, self.namespace)
        self.object_store.put(object_id, encode_fs_object(fs_object))
        return object_id

    def store_and_split_data_chunks(self, data: bytes) -> list[str]:
        """Split data into chunks, store each chunk, and return a list of their object IDs."""
        chunk_ids = []
        for i in range(0, len(data), MAX_DATA_CHUNK_PAYLOAD_SIZE):
            chunk_data = data[i:i + MAX_DATA_CHUNK_PAYLOAD_SIZE]
            chunk_object = DataChunkObject(object_type=OBJ_TYPE_DATA, data=chunk_data)
            chunk_id = self.store_fs_object(chunk_object)
            chunk_ids.append(chunk_id)
        return chunk_ids
