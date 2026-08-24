import time
from math import ceil

from slack_emoji_fs.file_system_models.data_chunk_object import DataChunkObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.object import OBJ_TYPE_DIRENT, OBJ_TYPE_DATA
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.tree_operations.errors import EntryExistsError, RootOperationError, CorruptTreeError, \
    IsDirectoryError, NotDirectoryError, DirectoryNotEmptyError, InvalidFileRangeError
from slack_emoji_fs.tree_operations.path import Path
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_objects import ResolvedPath, ParentResolution, ChunkRewriteResult
from slack_emoji_fs.tree_operations.tree_reader import TreeReader
from slack_emoji_fs.tree_operations.tree_snapshot import TreeSnapshot

class TreeWriter:
    def __init__(self, object_repository: ObjectRepository, tree_navigator: TreeNavigator) -> None:
        # Almost every method of TreeWriter will produce a new snapshot, so we pass snapshots in at the method level
        self._object_repository = object_repository
        self._tree_navigator = tree_navigator

    def _set_child(self, parent: ParentResolution, child_inode_id: str) -> str:
        """Replace (upsert) a child inode in a given directory, and rebuild ancestors up to the root inode, then return the new root inode id."""
        new_dirent_object = parent.resolved_parent_directory.dirent_object.model_copy(
            update={
                "entries": {
                    **parent.resolved_parent_directory.dirent_object.entries,
                    parent.child_name: child_inode_id,
                }
            }
        )
        new_dirent_id = self._object_repository.store_fs_object(new_dirent_object)
        new_dir_inode = parent.resolved_parent_directory.resolved_directory_inode.inode_object.model_copy(
            update={"dirent_object_id": new_dirent_id}
        )
        return self._rebuild_ancestors(parent.parent_path, self._object_repository.store_fs_object(new_dir_inode))

    def _rebuild_ancestors(
            self,
            path_to_changed_inode: ResolvedPath,
            replacement_inode_id: str,
    ) -> str:
        """Rebuilds the ancestors of the given path to new inode_id."""
        replacement_id = replacement_inode_id
        for step in reversed(path_to_changed_inode.steps):
            new_entries = step.parent_resolved_directory.dirent_object.model_copy(
                update={
                    "entries": {
                        **step.parent_resolved_directory.dirent_object.entries,
                        step.child_name: replacement_id,
                    }
                }
            )
            new_dirent_id = self._object_repository.store_fs_object(new_entries)
            new_dir_inode = step.parent_resolved_directory.resolved_directory_inode.inode_object.model_copy(
                update={"dirent_object_id": new_dirent_id}
            )
            replacement_id = self._object_repository.store_fs_object(new_dir_inode)
        return replacement_id

    def _publish_root(self, snapshot: TreeSnapshot, new_root_inode_id: str) -> TreeSnapshot:
        """Create a new root object from a given root inode id, and generate a snapshot."""
        new_root_object = RootObject(
            parent_root_id=snapshot.root_object_id,
            root_inode_id=new_root_inode_id,
        )
        new_root_object_id = self._object_repository.store_fs_object(new_root_object)
        return TreeSnapshot(self._object_repository, new_root_object_id, root_object=new_root_object)

    def create_file(
            self,
            tree_snapshot: TreeSnapshot,
            raw_path: str,
            *,
            mode: int,
            uid: int,
            gid: int,
            contents: bytes = b"",
    ) -> TreeSnapshot:
        """Creates a new file with the specified contents at the given path, and returns the new snapshot containing those updates."""
        resolved_parent_path = self._tree_navigator.resolve_parent(tree_snapshot.root_inode_id, raw_path)
        # File must not yet exist at location
        if resolved_parent_path.child_name in resolved_parent_path.resolved_parent_directory.dirent_object.entries:
            raise EntryExistsError("Tried to create a file that already exists.")
        file_chunks = self._object_repository.store_and_split_data_chunks(contents)
        file_inode = FileInodeObject(
            mode=mode,
            uid=uid,
            gid=gid,
            mtime=int(time.time()),
            ctime=int(time.time()),
            chunks=file_chunks,
            size=len(contents)
        )
        return self._publish_root(tree_snapshot, self._set_child(resolved_parent_path,
                                                                 self._object_repository.store_fs_object(file_inode)))

    def create_directory(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
            *,
            mode: int,
            uid: int,
            gid: int,
    ) -> TreeSnapshot:
        """Creates a new empty directory at the given path, and returns the new snapshot containing those updates."""
        resolved_parent_path = self._tree_navigator.resolve_parent(tree_snapshot.root_inode_id, path)
        # Directory must not yet exist at location
        if resolved_parent_path.child_name in resolved_parent_path.resolved_parent_directory.dirent_object.entries:
            raise EntryExistsError("Tried to create a directory that already exists.")
        new_dirent_object = DirectoryEntryObject(object_type=OBJ_TYPE_DIRENT, entries={})
        new_dirent_id = self._object_repository.store_fs_object(new_dirent_object)
        new_dir_inode = DirectoryInodeObject(
            mode=mode,
            uid=uid,
            gid=gid,
            mtime=int(time.time()),
            ctime=int(time.time()),
            dirent_object_id=new_dirent_id,
        )
        return self._publish_root(tree_snapshot, self._set_child(resolved_parent_path,
                                                                 self._object_repository.store_fs_object(
                                                                     new_dir_inode)))

    def _rewrite_file_chunks(
            self,
            existing_file: FileInodeObject,
            new_file_contents: bytes,
            rewrite_from_offset: int,
    ) -> ChunkRewriteResult:
        """Recreates affected chunks in the object repository for a file update."""
        new_file_chunk_ids = []
        for file_chunk_index in range(0, ceil(len(new_file_contents) / MAX_DATA_CHUNK_PAYLOAD_SIZE)):
            file_chunk_start = file_chunk_index * MAX_DATA_CHUNK_PAYLOAD_SIZE
            file_chunk_end = file_chunk_start + MAX_DATA_CHUNK_PAYLOAD_SIZE
            if file_chunk_end <= rewrite_from_offset:
                # Chunk is not affected
                new_file_chunk_ids.append(existing_file.chunks[file_chunk_index])
            else:
                # Create a new chunk
                chunk_contents = new_file_contents[file_chunk_start:file_chunk_end]
                chunk_object = DataChunkObject(object_type=OBJ_TYPE_DATA, data=chunk_contents)
                chunk_id = self._object_repository.store_fs_object(chunk_object)
                new_file_chunk_ids.append(chunk_id)
        return ChunkRewriteResult(new_file_chunk_ids, len(new_file_chunk_ids))

    def write_file(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
            data: bytes,
            *,
            offset: int = 0
    ) -> TreeSnapshot:
        """Writes to an existing file at the given path, and returns the new snapshot containing those updates."""
        if offset < 0:
            raise InvalidFileRangeError("Cannot write to a negative offset.")

        resolved_file_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, path)
        tree_reader = TreeReader(self._object_repository, self._tree_navigator, tree_snapshot)
        target_file_inode = resolved_file_path.target_inode.inode_object
        if isinstance(target_file_inode, DirectoryInodeObject):
            raise IsDirectoryError("Cannot write to a directory.")
        existing_file_contents = tree_reader.read_file_inode(target_file_inode)
        new_file_contents = existing_file_contents[:offset] + data + existing_file_contents[offset + len(data):]
        chunk_rewrite_result = self._rewrite_file_chunks(target_file_inode, new_file_contents, offset)
        new_file_inode = target_file_inode.model_copy(
            update={
                "chunks": chunk_rewrite_result.chunk_ids,
                "size": len(new_file_contents),
            }
        )
        return self._publish_root(tree_snapshot, self._rebuild_ancestors(resolved_file_path,
                                                                         self._object_repository.store_fs_object(
                                                                             new_file_inode)))

    def replace_file(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
            contents: bytes,
    ) -> TreeSnapshot:
        """Replace a file's complete contents and publish the result as one snapshot."""
        resolved_file_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, path)
        target_file_inode = resolved_file_path.target_inode.inode_object
        if isinstance(target_file_inode, DirectoryInodeObject):
            raise IsDirectoryError("Cannot replace the contents of a directory.")

        new_file_inode = target_file_inode.model_copy(
            update={
                "chunks": self._object_repository.store_and_split_data_chunks(contents),
                "size": len(contents),
            }
        )
        return self._publish_root(
            tree_snapshot,
            self._rebuild_ancestors(
                resolved_file_path,
                self._object_repository.store_fs_object(new_file_inode),
            ),
        )

    def truncate_file(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
            size: int
    ) -> TreeSnapshot:
        """Truncates an existing file at the given path, and returns the new snapshot containing those updates."""
        if size < 0:
            raise InvalidFileRangeError("Cannot truncate to a negative size.")

        resolved_file_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, path)
        tree_reader = TreeReader(self._object_repository, self._tree_navigator, tree_snapshot)
        target_file_inode = resolved_file_path.target_inode.inode_object
        if isinstance(target_file_inode, DirectoryInodeObject):
            raise IsDirectoryError("Cannot truncate a directory.")
        existing_file_contents = tree_reader.read_file_inode(target_file_inode)
        if len(existing_file_contents) == size:
            # Do nothing
            return tree_snapshot
        elif len(existing_file_contents) > size:
            new_file_contents = existing_file_contents[:size]
        else:
            new_file_contents = existing_file_contents + b"\0" * (size - len(existing_file_contents))
        chunk_rewrite_result = self._rewrite_file_chunks(target_file_inode, new_file_contents, size)
        new_file_inode = target_file_inode.model_copy(
            update={
                "chunks": chunk_rewrite_result.chunk_ids,
                "size": len(new_file_contents),
            }
        )
        return self._publish_root(tree_snapshot, self._rebuild_ancestors(resolved_file_path,
                                                                         self._object_repository.store_fs_object(
                                                                             new_file_inode)))

    def _remove_resolved_child(
            self,
            resolved_path: ResolvedPath,
    ) -> str:
        """
        In our tree-based copy-on-write filesystem, unlink and rmdir are effectively the same operation, so they share this helper.
        This returns a new root inode id to publish.
        """
        if len(resolved_path.steps) == 0:
            raise RootOperationError("Tried to remove a child in a nil directory.")
        parent_dirent_object = resolved_path.steps[-1].parent_resolved_directory.dirent_object
        new_dirent_object = parent_dirent_object.model_copy(
            update={
                "entries": {
                    entry_name: entry_id
                    for entry_name, entry_id in parent_dirent_object.entries.items()
                    if entry_name != resolved_path.steps[-1].child_name
                }
            }
        )
        new_dirent_id = self._object_repository.store_fs_object(new_dirent_object)
        new_dir_inode = resolved_path.steps[
            -1].parent_resolved_directory.resolved_directory_inode.inode_object.model_copy(
            update={"dirent_object_id": new_dirent_id}
        )
        parent_path = resolved_path.parent_path
        if not parent_path:
            raise CorruptTreeError("Could not find parent directory of child to remove.")
        return self._rebuild_ancestors(parent_path, self._object_repository.store_fs_object(new_dir_inode))

    def unlink_file(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
    ) -> TreeSnapshot:
        """Unlinks an existing file at the given path, and returns the new snapshot containing those updates."""
        resolved_file_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, path)
        if isinstance(resolved_file_path.target_inode.inode_object, DirectoryInodeObject):
            raise IsDirectoryError("Tried to unlink a directory. Use rmdir instead.")
        return self._publish_root(tree_snapshot, self._remove_resolved_child(resolved_file_path))

    def remove_directory(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
    ) -> TreeSnapshot:
        """Removes an existing directory at the given path, and returns the new snapshot containing those updates."""
        if Path(path).is_root:
            raise RootOperationError("Cannot remove the root directory.")
        resolved_dir_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, path)
        resolved_dir_inode = resolved_dir_path.target_inode.inode_object
        if isinstance(resolved_dir_inode, FileInodeObject):
            raise NotDirectoryError("Tried to rmdir a file. Use unlink instead.")
        target_dirent_object = self._object_repository.load_dirent_object(resolved_dir_inode.dirent_object_id)
        if len(target_dirent_object.entries) > 0:
            raise DirectoryNotEmptyError("Tried to remove a directory that is not empty.")
        return self._publish_root(tree_snapshot, self._remove_resolved_child(resolved_dir_path))

    def rename(
            self,
            tree_snapshot: TreeSnapshot,
            source_path: str,
            destination_path: str,
            *,
            replace: bool = False,
    ) -> TreeSnapshot:
        """Move or rename an entry, potentially replacing an existing entry at the new path. Returns the new snapshot containing those updates."""
        resolved_source_path = self._tree_navigator.trace(tree_snapshot.root_inode_id, source_path)


        # If we aren't replacing, then we need to ensure that the destination doesn't yet exist
        if not replace:
            # We'll need to re-query this on the new post-removal tree after removing the source entry, so we don't want to accidentally re-use this resolved path
            _resolved_destination_parent_path = self._tree_navigator.resolve_parent(tree_snapshot.root_inode_id, destination_path)
            if _resolved_destination_parent_path.child_name in _resolved_destination_parent_path.resolved_parent_directory.dirent_object.entries:
                raise EntryExistsError("Tried to rename with replace disabled, but an existing object exists at the destination.")

        target_inode_id = resolved_source_path.target_inode.object_id
        root_inode_id_with_removed_source = self._remove_resolved_child(resolved_source_path)

        resolved_destination_parent_path = self._tree_navigator.resolve_parent(root_inode_id_with_removed_source, destination_path)
        return self._publish_root(
            tree_snapshot,
            self._set_child(resolved_destination_parent_path, target_inode_id)
        )

    def chmod(
            self,
            tree_snapshot: TreeSnapshot,
            path: str,
            mode: int,
    ) -> TreeSnapshot:
        """Change the mode of a file."""
        resolved_path = self._tree_navigator.trace(
            tree_snapshot.root_inode_id,
            path,
        )
        normalized_mode = mode & 0o7777
        if resolved_path.target_inode.inode_object.mode == normalized_mode:
            return tree_snapshot

        updated_inode = resolved_path.target_inode.inode_object.model_copy(
            update={
                "mode": normalized_mode,
                "ctime": int(time.time()),
            }
        )
        updated_inode_id = self._object_repository.store_fs_object(updated_inode)
        updated_root_inode_id = self._rebuild_ancestors(
            resolved_path,
            updated_inode_id,
        )
        return self._publish_root(tree_snapshot, updated_root_inode_id)
