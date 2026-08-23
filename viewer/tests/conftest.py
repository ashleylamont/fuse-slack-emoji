from __future__ import annotations

from dataclasses import dataclass

import pytest

from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.object_repository import object_ids
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore


@dataclass(frozen=True)
class HistoryFixture:
    repository: ObjectRepository
    first_root_id: str
    latest_root_id: str
    root_inode_id: str
    docs_inode_id: str
    note_inode_id: str
    note_chunk_ids: tuple[str, ...]


def _directory(repository: ObjectRepository, entries: dict[str, str]) -> str:
    dirent_id = repository.store_fs_object(DirectoryEntryObject(entries=entries))
    return repository.store_fs_object(
        DirectoryInodeObject(
            dirent_object_id=dirent_id,
            mode=0o755,
            uid=1000,
            gid=1000,
            mtime=10,
            ctime=11,
        )
    )


def _file(repository: ObjectRepository, contents: bytes) -> tuple[str, tuple[str, ...]]:
    chunk_ids = tuple(repository.store_and_split_data_chunks(contents))
    inode_id = repository.store_fs_object(
        FileInodeObject(
            chunks=list(chunk_ids),
            size=len(contents),
            mode=0o640,
            uid=1000,
            gid=1001,
            mtime=20,
            ctime=21,
        )
    )
    return inode_id, chunk_ids


@pytest.fixture
def history_fixture(monkeypatch: pytest.MonkeyPatch) -> HistoryFixture:
    repository = ObjectRepository(MemoryObjectStore(), namespace="viewer")

    empty_root_inode_id = _directory(repository, {})
    monkeypatch.setattr(object_ids.time, "time", lambda: 100.0)
    first_root_id = repository.store_fs_object(
        RootObject(parent_root_id=None, root_inode_id=empty_root_inode_id)
    )

    note_inode_id, note_chunk_ids = _file(repository, b"hello from history\n")
    docs_inode_id = _directory(repository, {"note.txt": note_inode_id})
    other_inode_id, _ = _file(repository, b"other")
    root_inode_id = _directory(repository, {"zeta.txt": other_inode_id, "docs": docs_inode_id})

    monkeypatch.setattr(object_ids.time, "time", lambda: 200.0)
    latest_root_id = repository.store_fs_object(
        RootObject(parent_root_id=first_root_id, root_inode_id=root_inode_id)
    )

    return HistoryFixture(
        repository=repository,
        first_root_id=first_root_id,
        latest_root_id=latest_root_id,
        root_inode_id=root_inode_id,
        docs_inode_id=docs_inode_id,
        note_inode_id=note_inode_id,
        note_chunk_ids=note_chunk_ids,
    )
