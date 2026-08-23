from __future__ import annotations

import pytest

from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.memory_object_store import MemoryObjectStore
from slack_emoji_fs.file_system_models.root_object import RootObject
from slack_emoji_fs.object_repository import object_ids
from slack_emoji_fs_viewer.history import HistoryViewer

from .conftest import HistoryFixture, _directory, _file


def test_empty_repository_has_no_snapshots() -> None:
    viewer = HistoryViewer(ObjectRepository(MemoryObjectStore(), "empty"))

    assert viewer.list_snapshots() == ()
    assert viewer.latest_snapshot() is None
    assert viewer.list_heads() == ()
    assert viewer.root_history() == ()


def test_snapshots_heads_and_parent_history(history_fixture: HistoryFixture) -> None:
    viewer = HistoryViewer(history_fixture.repository)

    snapshots = viewer.list_snapshots()
    assert [snapshot.root_object_id for snapshot in snapshots] == [
        history_fixture.latest_root_id,
        history_fixture.first_root_id,
    ]
    assert snapshots[0].created_at == 200.0
    assert snapshots[1].created_at == 100.0
    assert viewer.latest_snapshot() == snapshots[0]
    assert [snapshot.root_object_id for snapshot in viewer.list_heads()] == [
        history_fixture.latest_root_id
    ]
    assert [snapshot.root_object_id for snapshot in viewer.root_history()] == [
        history_fixture.latest_root_id,
        history_fixture.first_root_id,
    ]
    assert [snapshot.root_object_id for snapshot in viewer.root_history(history_fixture.first_root_id)] == [
        history_fixture.first_root_id
    ]


def test_materialize_tree_exposes_structure_metadata_and_references(
    history_fixture: HistoryFixture,
) -> None:
    tree = HistoryViewer(history_fixture.repository).materialize_tree(history_fixture.latest_root_id)

    assert (tree.name, tree.path, tree.kind) == ("/", "/", "directory")
    assert tree.inode_object_id == history_fixture.root_inode_id
    assert [child.name for child in tree.children] == ["docs", "zeta.txt"]

    docs = tree.children[0]
    note = docs.children[0]
    assert docs.inode_object_id == history_fixture.docs_inode_id
    assert (note.name, note.path, note.kind) == ("note.txt", "/docs/note.txt", "file")
    assert note.inode_object_id == history_fixture.note_inode_id
    assert note.mode == 0o640
    assert note.uid == 1000
    assert note.gid == 1001
    assert note.size == len(b"hello from history\n")
    assert note.chunk_object_ids == history_fixture.note_chunk_ids
    assert note.children == ()


def test_diff_from_parent_reports_visible_path_changes(
    history_fixture: HistoryFixture,
) -> None:
    """A snapshot diff reports new paths without flagging rebuilt ancestor directories."""
    diff = HistoryViewer(history_fixture.repository).diff_from_parent(
        history_fixture.latest_root_id
    )

    assert diff.parent_root_id == history_fixture.first_root_id
    assert diff.added_paths == ("/docs", "/docs/note.txt", "/zeta.txt")
    assert diff.removed_paths == ()
    assert diff.modified_paths == ()
    assert diff.tree.path == "/"


def test_diff_distinguishes_modified_and_removed_paths(
    history_fixture: HistoryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content changes and removals are distinct without marking rebuilt directories."""
    repository = history_fixture.repository
    changed_note_id, _ = _file(repository, b"changed contents\n")
    docs_inode_id = _directory(repository, {"note.txt": changed_note_id})
    root_inode_id = _directory(repository, {"docs": docs_inode_id})
    monkeypatch.setattr(object_ids.time, "time", lambda: 300.0)
    root_id = repository.store_fs_object(RootObject(
        parent_root_id=history_fixture.latest_root_id,
        root_inode_id=root_inode_id,
    ))

    diff = HistoryViewer(repository).diff_from_parent(root_id)

    assert diff.added_paths == ()
    assert diff.removed_paths == ("/zeta.txt",)
    assert diff.modified_paths == ("/docs/note.txt",)
