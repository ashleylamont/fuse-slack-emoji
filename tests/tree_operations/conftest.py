from dataclasses import dataclass

import pytest

from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_reader import TreeReader
from slack_emoji_fs.tree_operations.tree_snapshot import TreeSnapshot


@dataclass(frozen=True)
class SampleTree:
    repository: ObjectRepository
    navigator: TreeNavigator
    reader: TreeReader
    root_inode_id: str
    documents_inode_id: str
    readme_inode_id: str
    blob_inode_id: str


def _directory_inode(dirent_object_id: str) -> DirectoryInodeObject:
    return DirectoryInodeObject(
        dirent_object_id=dirent_object_id,
        mode=0o755,
        uid=1000,
        gid=1000,
        mtime=1,
        ctime=2,
    )


def _file_inode(chunk_ids: list[str], size: int) -> FileInodeObject:
    return FileInodeObject(
        chunks=chunk_ids,
        size=size,
        mode=0o644,
        uid=1000,
        gid=1000,
        mtime=1,
        ctime=2,
    )


@pytest.fixture
def sample_tree() -> SampleTree:
    repository = ObjectRepository(MemoryObjectStore(), namespace="tests")

    readme_data = b"read me\n"
    readme_inode_id = repository.store_fs_object(
        _file_inode(repository.store_and_split_data_chunks(readme_data), len(readme_data))
    )
    blob_data = b"a" * MAX_DATA_CHUNK_PAYLOAD_SIZE + b"bcdef"
    blob_inode_id = repository.store_fs_object(
        _file_inode(repository.store_and_split_data_chunks(blob_data), len(blob_data))
    )

    documents_entries_id = repository.store_fs_object(
        DirectoryEntryObject(entries={"readme.txt": readme_inode_id})
    )
    documents_inode_id = repository.store_fs_object(_directory_inode(documents_entries_id))
    root_entries_id = repository.store_fs_object(
        DirectoryEntryObject(entries={"documents": documents_inode_id, "blob": blob_inode_id})
    )
    root_inode_id = repository.store_fs_object(_directory_inode(root_entries_id))
    root_object_id = repository.store_fs_object(
        RootObject(parent_root_id=None, root_inode_id=root_inode_id)
    )

    snapshot = TreeSnapshot(repository, root_object_id)
    navigator = TreeNavigator(repository)
    return SampleTree(
        repository=repository,
        navigator=navigator,
        reader=TreeReader(repository, navigator, snapshot),
        root_inode_id=root_inode_id,
        documents_inode_id=documents_inode_id,
        readme_inode_id=readme_inode_id,
        blob_inode_id=blob_inode_id,
    )
