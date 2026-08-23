"""Read-only values exposed by the object history viewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


type NodeKind = Literal["directory", "file"]


@dataclass(frozen=True, slots=True)
class RootReference:
    """A root discovered from its object ID without fetching its payload."""

    root_object_id: str
    created_at: float


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    """The identity and lineage of one immutable filesystem snapshot."""

    root_object_id: str
    root_inode_id: str
    parent_root_id: str | None
    created_at: float


@dataclass(frozen=True, slots=True)
class TreeNode:
    """A fully materialized inode and its storage-level references."""

    name: str
    path: str
    kind: NodeKind
    inode_object_id: str
    mode: int
    uid: int
    gid: int
    mtime: int
    ctime: int
    size: int | None = None
    chunk_object_ids: tuple[str, ...] = ()
    dirent_object_id: str | None = None
    children: tuple[TreeNode, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    """A materialized snapshot and its path-level changes from its parent."""

    root_object_id: str
    parent_root_id: str | None
    tree: TreeNode
    added_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
