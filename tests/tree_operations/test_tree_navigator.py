import pytest

from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from slack_emoji_fs.tree_operations.errors import (
    InvalidPathError,
    NotDirectoryError,
    PathNotFoundError,
    RootOperationError,
)
from slack_emoji_fs.tree_operations.path import Path


def test_path_normalizes_repeated_and_trailing_slashes() -> None:
    """Paths canonicalize redundant separators while preserving their components."""
    path = Path("//documents///readme.txt/")

    assert path.parts == ("documents", "readme.txt")
    assert path.raw_path == "/documents/readme.txt"
    assert path.name == "readme.txt"
    assert path.parent_path is not None
    assert path.parent_path.raw_path == "/documents"


@pytest.mark.parametrize("raw_path", ["", "relative", "a/b", "/a/./b", "/a/../b", "/nul\0path"])
def test_path_rejects_invalid_syntax(raw_path: str) -> None:
    """Malformed, relative, dot-segment, and NUL-containing paths are rejected."""
    with pytest.raises(InvalidPathError):
        Path(raw_path)


def test_root_path_name_is_rejected() -> None:
    """The root path has no final component name."""
    root = Path("/")

    with pytest.raises(RootOperationError):
        _ = root.name


def test_root_path_parent_parts_are_rejected() -> None:
    """The root path has no parent component sequence."""
    root = Path("/")

    with pytest.raises(RootOperationError):
        _ = root.parent_parts


def test_root_path_parent_is_rejected() -> None:
    """The root path has no parent path."""
    root = Path("/")

    with pytest.raises(RootOperationError):
        _ = root.parent_path


def test_trace_and_resolve_preserve_all_ids_needed_for_traversal(sample_tree) -> None:
    """A traversal trace retains each resolved inode and child name."""
    trace = sample_tree.navigator.trace(sample_tree.root_inode_id, "/documents/readme.txt")

    assert trace.target_inode.object_id == sample_tree.readme_inode_id
    assert isinstance(trace.target_inode.inode_object, FileInodeObject)
    assert [step.child_name for step in trace.steps] == ["documents", "readme.txt"]
    assert trace.steps[0].child_resolved_inode.object_id == sample_tree.documents_inode_id
    assert trace.steps[1].child_resolved_inode.object_id == sample_tree.readme_inode_id


def test_root_and_directory_resolution(sample_tree) -> None:
    """Resolution returns the root and directory inode plus its directory entries."""
    root = sample_tree.navigator.resolve(sample_tree.root_inode_id, "/")
    documents = sample_tree.navigator.resolve_directory(sample_tree.root_inode_id, "/documents")

    assert root.object_id == sample_tree.root_inode_id
    assert isinstance(root.inode_object, DirectoryInodeObject)
    assert documents.resolved_directory_inode.object_id == sample_tree.documents_inode_id
    assert documents.dirent_object.entries == {"readme.txt": sample_tree.readme_inode_id}


def test_resolve_parent_handles_root_level_and_nested_paths(sample_tree) -> None:
    """Parent resolution identifies the containing directory and requested child name."""
    root_parent = sample_tree.navigator.resolve_parent(sample_tree.root_inode_id, "/blob")
    nested_parent = sample_tree.navigator.resolve_parent(sample_tree.root_inode_id, "/documents/new.txt")

    assert root_parent.child_name == "blob"
    assert root_parent.resolved_parent_directory.resolved_directory_inode.object_id == sample_tree.root_inode_id
    assert nested_parent.child_name == "new.txt"
    assert nested_parent.resolved_parent_directory.resolved_directory_inode.object_id == sample_tree.documents_inode_id


def test_navigation_reports_missing_and_non_directory_components(sample_tree) -> None:
    """Navigation distinguishes missing paths, file components, and root parent requests."""
    with pytest.raises(PathNotFoundError):
        sample_tree.navigator.resolve(sample_tree.root_inode_id, "/documents/missing")
    with pytest.raises(NotDirectoryError):
        sample_tree.navigator.resolve(sample_tree.root_inode_id, "/blob/child")
    with pytest.raises(NotDirectoryError):
        sample_tree.navigator.resolve_directory(sample_tree.root_inode_id, "/blob")
    with pytest.raises(RootOperationError):
        sample_tree.navigator.resolve_parent(sample_tree.root_inode_id, "/")


def test_navigation_performs_no_writes(sample_tree) -> None:
    """Navigation is read-only and leaves the object store unchanged."""
    store = sample_tree.repository.object_store
    before = list(store.list_ids())

    sample_tree.navigator.resolve(sample_tree.root_inode_id, "/documents/readme.txt")

    assert store.list_ids() == before
