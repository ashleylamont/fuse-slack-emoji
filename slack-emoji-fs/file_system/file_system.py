from __future__ import annotations

from file_system_models.directory_entry_object import DirectoryEntryObject
from file_system_models.directory_inode import DirectoryInodeObject
from file_system_models.object import OBJ_TYPE_ROOT
from file_system_models.root_object import RootObject
from object_repository.object_repository import ObjectRepository
from tree_operations.tree_navigator import TreeNavigator
from tree_operations.tree_objects import ResolvedInode
from tree_operations.tree_reader import TreeReader
from tree_operations.tree_snapshot import TreeSnapshot
from tree_operations.tree_writer import TreeWriter
import time


class FileSystem:
    def __init__(
            self,
            object_repository: ObjectRepository,
            tree_navigator: TreeNavigator,
            tree_writer: TreeWriter,
            initial_snapshot: TreeSnapshot
    ) -> None:
        self._object_repository = object_repository
        self._tree_navigator = tree_navigator
        self._tree_writer = tree_writer
        self._tree_snapshot = initial_snapshot

    @staticmethod
    def create_from_latest_root_or_new(
            object_repository: ObjectRepository,
            tree_navigator: TreeNavigator,
            tree_writer: TreeWriter,
    ) -> FileSystem:
        """Initialise a new FileSystem instance by reading the latest root or creating a new empty root."""
        latest_root_id = object_repository.object_store_accessor.query().with_object_type(OBJ_TYPE_ROOT).sort_by_timestamp().first_object_id()
        if latest_root_id is None:
            # Create a new empty root
            new_root_dirent = DirectoryEntryObject(entries={})
            new_root_dirent_id = object_repository.store_fs_object(new_root_dirent)
            new_root_inode = DirectoryInodeObject(
                mode=0o755, # todo: change this probs
                uid=0,
                gid=0,
                mtime=int(time.time()),
                ctime=int(time.time()),
                dirent_object_id=new_root_dirent_id,
            )
            new_root_inode_id = object_repository.store_fs_object(new_root_inode)
            new_root = RootObject(
                parent_root_id=None,
                root_inode_id=new_root_inode_id
            )
            new_root_id = object_repository.store_fs_object(new_root)
            snapshot = TreeSnapshot(object_repository, new_root_id, root_object=new_root)
        else:
            snapshot = TreeSnapshot(object_repository, latest_root_id)
        return FileSystem(object_repository, tree_navigator, tree_writer, snapshot)

    @property
    def current_snapshot(self) -> TreeSnapshot:
        return self._tree_snapshot

    @property
    def _tree_reader(self) -> TreeReader:
        return TreeReader(self._object_repository, self._tree_navigator, self._tree_snapshot)

    def resolve(self, path: str) -> ResolvedInode:
        return self._tree_reader.resolve(path)

    def list_directory(self, path: str) -> tuple[str, ...]:
        return self._tree_reader.list_directory(path)

    def read_file(
            self,
            path: str,
            *,
            offset: int = 0,
            size: int | None = None,
    ) -> bytes:
        return self._tree_reader.read_file(path, offset=offset, size=size)

    def create_file(
            self,
            path: str,
            *,
            mode: int,
            uid: int,
            gid: int,
            contents: bytes = b"",
    ) -> None:
        self._tree_snapshot = self._tree_writer.create_file(self._tree_snapshot, path, mode=mode, uid=uid, gid=gid, contents=contents)

    def create_directory(
            self,
            path: str,
            *,
            mode: int,
            uid: int,
            gid: int,
    ) -> None:
        self._tree_snapshot = self._tree_writer.create_directory(self._tree_snapshot, path, mode=mode, uid=uid, gid=gid)

    def write_file(
            self,
            path: str,
            data: bytes,
            *,
            offset: int = 0,
    ) -> None:
        self._tree_snapshot = self._tree_writer.write_file(self._tree_snapshot, path, data, offset=offset)

    def truncate_file(self, path: str, size: int) -> None:
        self._tree_snapshot = self._tree_writer.truncate_file(self._tree_snapshot, path, size=size)

    def unlink_file(self, path: str) -> None:
        self._tree_snapshot = self._tree_writer.unlink_file(self._tree_snapshot, path)

    def remove_directory(self, path: str) -> None:
        self._tree_snapshot = self._tree_writer.remove_directory(self._tree_snapshot, path)

    def rename(self, source: str, destination: str, *, replace: bool = False) -> None:
        self._tree_snapshot = self._tree_writer.rename(self._tree_snapshot, source, destination, replace=replace)