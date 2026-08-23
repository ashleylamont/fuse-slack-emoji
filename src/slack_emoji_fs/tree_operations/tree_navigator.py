from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.tree_operations.path import Path
from slack_emoji_fs.tree_operations.tree_objects import AnyInodeObject, ResolvedPath, ResolvedInode, ResolvedDirectory, PathStep, ParentResolution
from slack_emoji_fs.tree_operations.errors import PathNotFoundError, NotDirectoryError, CorruptTreeError, RootOperationError


class TreeNavigator:
    def __init__(self, object_repository: ObjectRepository) -> None:
        self._object_repository = object_repository

    def _resolve_inode(self, inode_id: str) -> ResolvedInode[AnyInodeObject]:
        """Resolve an inode by id into a ResolvedInode object, which allows easily tracking its id later on"""
        inode_object = self._object_repository.load_inode_object(inode_id)
        return ResolvedInode(inode_object, inode_id)

    def _resolve_directory(self, resolved_directory_inode: ResolvedInode[AnyInodeObject]) -> ResolvedDirectory:
        """Resolve a directory from its inode."""
        if not isinstance(resolved_directory_inode.inode_object, DirectoryInodeObject):
            if isinstance(resolved_directory_inode.inode_object, FileInodeObject):
                raise NotDirectoryError("Called _resolve_directory on a non-directory inode object")
            else:
                raise CorruptTreeError("_resolve_directory encountered a non-inode object when it was expecting an inode")
        directory_entry = self._object_repository.load_dirent_object(resolved_directory_inode.inode_object.dirent_object_id)
        resolved_directory = ResolvedInode(
            resolved_directory_inode.inode_object,
            resolved_directory_inode.object_id,
        )
        return ResolvedDirectory(
            resolved_directory,
            directory_entry
        )

    def _follow_child(self, parent_resolved_directory: ResolvedDirectory, child_name: str) -> PathStep:
        """Follow a child object in a directory and return a PathStep."""
        if child_name not in parent_resolved_directory.dirent_object.entries:
            raise PathNotFoundError(f"The child object {child_name} was not found in the directory {parent_resolved_directory.resolved_directory_inode.object_id}.")
        child_inode_id = parent_resolved_directory.dirent_object.entries[child_name]
        child_resolved_inode = self._resolve_inode(child_inode_id)
        return PathStep(
            parent_resolved_directory,
            child_name,
            child_resolved_inode
        )


    def trace(self, root_inode_id: str, raw_path: str) -> ResolvedPath:
        """Resolve the full chain of nodes in a given path from a root inode."""
        path = Path(raw_path)
        path_chain: list[PathStep] = []

        root_directory = self._resolve_directory(self._resolve_inode(root_inode_id))

        current_directory = root_directory
        for (part_index, part) in enumerate(path.parts):
            next_path_step = self._follow_child(current_directory, part)
            path_chain.append(next_path_step)
            if part_index != len(path.parts) - 1:
                # We only resolve and update current_directory on non-last segments, as otherwise we'd potentially dir-resolve a file
                current_directory = self._resolve_directory(next_path_step.child_resolved_inode)

        return ResolvedPath(
            root_directory,
            tuple(path_chain)
        )

    def resolve(self, root_inode_id: str, raw_path: str) -> ResolvedInode[AnyInodeObject]:
        """Resolve a filesystem path to its corresponding inode object."""
        resolved_path = self.trace(root_inode_id, raw_path)
        return resolved_path.target_inode

    def resolve_directory(self, root_inode_id: str, raw_path: str) -> ResolvedDirectory:
        """Resolve a file system path to its corresponding inode object and require that the resolved object is a directory."""
        return self._resolve_directory(self.resolve(root_inode_id, raw_path))

    def resolve_parent(self, root_inode_id: str, raw_path: str) -> ParentResolution:
        """Resolve the *parent* path to a file, and return a ParentResolution object. This is safe for paths to files that haven't been created yet."""
        path = Path(raw_path)
        parent_path = path.parent_path
        if path.is_root or parent_path is None or path.name is None:
            raise RootOperationError("Tried to resolve parent of root path.")
        parent_resolved_path = self.trace(root_inode_id, parent_path.raw_path)
        parent_resolved_directory = self._resolve_directory(parent_resolved_path.target_inode)
        return ParentResolution(
            parent_resolved_directory,
            path.name,
            parent_resolved_path
        )
