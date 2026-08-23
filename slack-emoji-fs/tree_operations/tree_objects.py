from __future__ import annotations

from file_system_models.directory_entry_object import DirectoryEntryObject
from file_system_models.directory_inode import DirectoryInodeObject
from file_system_models.inode_object import InodeObject


class ResolvedInode[T: InodeObject]:
    def __init__(self, inode_object: T, object_id: str) -> None:
        self.inode_object = inode_object
        self.object_id = object_id


class ResolvedDirectory:
    def __init__(self, resolved_directory_inode: ResolvedInode[DirectoryInodeObject], dirent_object: DirectoryEntryObject):
        self.resolved_directory_inode = resolved_directory_inode
        self.dirent_object = dirent_object

class PathNotFoundException(Exception):
    pass

class PathStep:
    def __init__(
            self,
            parent_resolved_directory: ResolvedDirectory,
            child_name: str,
            child_resolved_inode: ResolvedInode
    ) -> None:
        self.parent_resolved_directory = parent_resolved_directory
        self.child_name = child_name
        self.child_resolved_inode = child_resolved_inode

class ResolvedPath:
    def __init__(
            self,
            root_directory: ResolvedDirectory,
            steps: tuple[PathStep, ...]
    ) -> None:
        self.root_directory = root_directory
        self.steps = steps
        self.target_inode = steps[-1].child_resolved_inode if len(steps) > 0 else root_directory.resolved_directory_inode

    @property
    def parent_path(self) -> ResolvedPath | None:
        if len(self.steps) == 0:
            return None
        return ResolvedPath(
            self.root_directory,
            self.steps[:-1]
        )

class ParentResolution:
    def __init__(
            self,
            resolved_parent_directory: ResolvedDirectory,
            child_name: str,
            parent_path: ResolvedPath
    ) -> None:
        self.resolved_parent_directory = resolved_parent_directory
        self.child_name = child_name
        self.parent_path = parent_path

class ChunkRewriteResult:
    def __init__(
            self,
            chunk_ids: tuple[str, ...],
            file_size: int
    ) -> None:
        self.chunk_ids = chunk_ids
        self.file_size = file_size