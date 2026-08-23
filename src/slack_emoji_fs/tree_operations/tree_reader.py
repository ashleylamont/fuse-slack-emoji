from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_objects import ResolvedInode
from slack_emoji_fs.tree_operations.tree_snapshot import TreeSnapshot


class TreeReader:
    def __init__(self, object_repository: ObjectRepository, tree_navigator: TreeNavigator, snapshot: TreeSnapshot) -> None:
        self._object_repository = object_repository
        self._tree_navigator = tree_navigator
        self.snapshot = snapshot

    def resolve(self, path: str) -> ResolvedInode:
        return self._tree_navigator.resolve(self.snapshot.root_inode_id, path)

    def list_directory(self, path: str) -> tuple[str, ...]:
        """Resolve a directory and return its contents."""
        resolved_directory = self._tree_navigator.resolve_directory(self.snapshot.root_inode_id, path)
        return ".", "..", *resolved_directory.dirent_object.entries.keys()

    def read_file(self, path: str, *, offset: int = 0, size: int | None = None) -> bytes:
        """Resolve a file object, and retrieve its data from relevant chunks."""
        resolved_file = self._tree_navigator.resolve(self.snapshot.root_inode_id, path)
        resolved_file_inode: FileInodeObject = resolved_file.inode_object
        if not isinstance(resolved_file_inode, FileInodeObject):
            raise Exception(f"Expected FileInodeObject but got {resolved_file_inode}")
        return self.read_file_inode(resolved_file_inode, offset=offset, size=size)

    def read_file_inode(self, file_inode: FileInodeObject, *, offset: int = 0, size: int | None = None) -> bytes:
        """Read the data of a file inode object from relevant chunks."""
        file_contents = b""
        starting_chunk = offset // MAX_DATA_CHUNK_PAYLOAD_SIZE
        starting_chunk_offset = offset % MAX_DATA_CHUNK_PAYLOAD_SIZE
        for chunk_index in range(starting_chunk, len(file_inode.chunks)):
            read_next_bytes = MAX_DATA_CHUNK_PAYLOAD_SIZE \
                if size is None else size - len(file_contents)
            chunk = self._object_repository.load_data_chunk_object(file_inode.chunks[chunk_index])
            file_contents += chunk.data[starting_chunk_offset:read_next_bytes+starting_chunk_offset] \
                if chunk_index == starting_chunk \
                else chunk.data[:read_next_bytes]
            if len(file_contents) == size:
                break
        return file_contents