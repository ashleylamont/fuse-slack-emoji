"""Read-only traversal of Slack Emoji FS roots and trees."""

from __future__ import annotations

from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.directory_entry_object import DirectoryEntryObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.file_system_models.object import OBJ_TYPE_ROOT
from slack_emoji_fs.object_repository.errors import InvalidObjectIdError, ObjectNotFoundError
from slack_emoji_fs.object_repository.object_ids import ObjectIdV1Standard
from slack_emoji_fs.object_repository.object_repository import ObjectRepository

from .models import RootReference, SnapshotDiff, SnapshotSummary, TreeNode


class HistoryCycleError(ValueError):
    """Raised when corrupt object references contain a cycle."""


class BrokenHistoryError(ValueError):
    """Raised when a root's declared parent cannot be loaded."""


class TreeMaterializationError(ValueError):
    """Raised when an object referenced by a tree cannot be materialized."""


class HistoryViewer:
    """Inspect snapshots and trees through an existing ``ObjectRepository``."""

    def __init__(self, object_repository: ObjectRepository) -> None:
        self._repository = object_repository

    def list_snapshots(self, *, descending: bool = True) -> tuple[SnapshotSummary, ...]:
        """Return every root object in the repository, ordered by creation time."""
        entries = self._root_entries(descending=descending)
        return tuple(self._snapshot_summary(object_id, created_at=timestamp) for object_id, timestamp in entries)

    def list_roots(self, *, descending: bool = True) -> tuple[RootReference, ...]:
        """List roots using object IDs only, without fetching root payloads."""
        return tuple(
            RootReference(root_object_id=object_id, created_at=timestamp)
            for object_id, timestamp in self._root_entries(descending=descending)
        )

    def _root_entries(self, *, descending: bool = True) -> list[tuple[str, float]]:
        """Find root IDs without fetching their object payloads."""
        entries: list[tuple[str, float]] = []
        for object_id in self._repository.object_store.list_ids():
            try:
                info = ObjectIdV1Standard.parse_id(object_id)
            except (InvalidObjectIdError, ValueError):
                continue
            if info.namespace == self._repository.namespace and info.object_type == OBJ_TYPE_ROOT:
                entries.append((object_id, info.timestamp))
        entries.sort(key=lambda entry: entry[1], reverse=descending)
        return entries

    def latest_snapshot(self) -> SnapshotSummary | None:
        """Return the newest history head, or ``None`` for an empty repository.

        Looking at heads avoids selecting a parent when multiple roots were created
        within the object ID timestamp's one-millisecond resolution.
        """
        heads = self.list_heads()
        return heads[0] if heads else None

    def list_heads(self) -> tuple[SnapshotSummary, ...]:
        """Return roots that are not the parent of another discovered root."""
        snapshots = self.list_snapshots()
        referenced_parents = {
            snapshot.parent_root_id
            for snapshot in snapshots
            if snapshot.parent_root_id is not None
        }
        return tuple(
            snapshot
            for snapshot in snapshots
            if snapshot.root_object_id not in referenced_parents
        )

    def root_history(self, root_object_id: str | None = None) -> tuple[SnapshotSummary, ...]:
        """Walk a root's parent chain from newest to oldest.

        When ``root_object_id`` is omitted, the newest discovered root is used.
        This differs from :meth:`list_snapshots`: unrelated roots are not included.
        """
        if root_object_id is None:
            latest = self.latest_snapshot()
            if latest is None:
                return ()
            root_object_id = latest.root_object_id

        history: list[SnapshotSummary] = []
        visited: set[str] = set()
        current_id: str | None = root_object_id
        while current_id is not None:
            if current_id in visited:
                raise HistoryCycleError(f"Root history contains a cycle at {current_id}")
            visited.add(current_id)
            try:
                summary = self._snapshot_summary(current_id)
            except ObjectNotFoundError as error:
                raise BrokenHistoryError(
                    f"Root history references missing object {current_id}"
                ) from error
            history.append(summary)
            current_id = summary.parent_root_id
        return tuple(history)

    def materialize_tree(self, root_object_id: str) -> TreeNode:
        """Recursively load the tree referenced by a root object.

        File contents are intentionally not loaded. File nodes expose their ordered
        chunk object IDs so a UI can display storage structure without extra reads.
        """
        try:
            root = self._repository.load_root_object(root_object_id)
        except Exception as error:
            raise TreeMaterializationError(
                f"Could not load root object {root_object_id}"
            ) from error
        return self._materialize_inode(
            inode_object_id=root.root_inode_id,
            name="/",
            path="/",
            ancestors=frozenset(),
            inode_cache={},
            dirent_cache={},
        )

    def diff_from_parent(self, root_object_id: str) -> SnapshotDiff:
        """Materialize a snapshot and compare its visible paths with its parent."""
        summary = self._snapshot_summary(root_object_id)
        tree = self.materialize_tree(root_object_id)
        current_nodes = self._nodes_by_path(tree)

        if summary.parent_root_id is None:
            return SnapshotDiff(
                root_object_id=root_object_id,
                parent_root_id=None,
                tree=tree,
                added_paths=tuple(sorted(path for path in current_nodes if path != "/")),
                removed_paths=(),
                modified_paths=(),
            )

        parent_tree = self.materialize_tree(summary.parent_root_id)
        parent_nodes = self._nodes_by_path(parent_tree)
        current_paths = current_nodes.keys()
        parent_paths = parent_nodes.keys()
        return SnapshotDiff(
            root_object_id=root_object_id,
            parent_root_id=summary.parent_root_id,
            tree=tree,
            added_paths=tuple(sorted(current_paths - parent_paths)),
            removed_paths=tuple(sorted(parent_paths - current_paths)),
            modified_paths=tuple(sorted(
                path
                for path in current_paths & parent_paths
                if self._visible_node_state(current_nodes[path])
                != self._visible_node_state(parent_nodes[path])
            )),
        )

    @classmethod
    def _nodes_by_path(cls, tree: TreeNode) -> dict[str, TreeNode]:
        nodes = {tree.path: tree}
        for child in tree.children:
            nodes.update(cls._nodes_by_path(child))
        return nodes

    @staticmethod
    def _visible_node_state(node: TreeNode) -> tuple[object, ...]:
        """Exclude storage IDs and children so structural sharing is not a false change."""
        return (
            node.kind,
            node.mode,
            node.uid,
            node.gid,
            node.mtime,
            node.ctime,
            node.size,
            node.chunk_object_ids,
        )

    def _snapshot_summary(
        self,
        root_object_id: str,
        *,
        created_at: float | None = None,
    ) -> SnapshotSummary:
        root = self._repository.load_root_object(root_object_id)
        timestamp = (
            ObjectIdV1Standard.parse_id(root_object_id).timestamp
            if created_at is None
            else created_at
        )
        return SnapshotSummary(
            root_object_id=root_object_id,
            root_inode_id=root.root_inode_id,
            parent_root_id=root.parent_root_id,
            created_at=timestamp,
        )

    def _materialize_inode(
        self,
        *,
        inode_object_id: str,
        name: str,
        path: str,
        ancestors: frozenset[str],
        inode_cache: dict[str, FileInodeObject | DirectoryInodeObject],
        dirent_cache: dict[str, DirectoryEntryObject],
    ) -> TreeNode:
        if inode_object_id in ancestors:
            raise HistoryCycleError(f"Tree contains an inode cycle at {inode_object_id}")

        try:
            inode = inode_cache.get(inode_object_id)
            if inode is None:
                inode = self._repository.load_inode_object(inode_object_id)
                inode_cache[inode_object_id] = inode
        except Exception as error:
            raise TreeMaterializationError(
                f"Could not load inode {inode_object_id} at {path}"
            ) from error
        if isinstance(inode, FileInodeObject):
            return TreeNode(
                name=name,
                path=path,
                kind="file",
                inode_object_id=inode_object_id,
                mode=inode.mode,
                uid=inode.uid,
                gid=inode.gid,
                mtime=inode.mtime,
                ctime=inode.ctime,
                size=inode.size,
                chunk_object_ids=tuple(inode.chunks),
            )

        if not isinstance(inode, DirectoryInodeObject):
            raise TypeError(f"Unsupported inode type for {inode_object_id}")

        try:
            dirent = dirent_cache.get(inode.dirent_object_id)
            if dirent is None:
                dirent = self._repository.load_dirent_object(inode.dirent_object_id)
                dirent_cache[inode.dirent_object_id] = dirent
        except Exception as error:
            raise TreeMaterializationError(
                f"Could not load directory entries {inode.dirent_object_id} at {path}"
            ) from error
        next_ancestors = ancestors | {inode_object_id}
        children = tuple(
            self._materialize_inode(
                inode_object_id=child_inode_id,
                name=child_name,
                path=self._child_path(path, child_name),
                ancestors=next_ancestors,
                inode_cache=inode_cache,
                dirent_cache=dirent_cache,
            )
            for child_name, child_inode_id in sorted(dirent.entries.items())
        )
        return TreeNode(
            name=name,
            path=path,
            kind="directory",
            inode_object_id=inode_object_id,
            mode=inode.mode,
            uid=inode.uid,
            gid=inode.gid,
            mtime=inode.mtime,
            ctime=inode.ctime,
            dirent_object_id=inode.dirent_object_id,
            children=children,
        )

    @staticmethod
    def _child_path(parent_path: str, child_name: str) -> str:
        return f"/{child_name}" if parent_path == "/" else f"{parent_path}/{child_name}"
