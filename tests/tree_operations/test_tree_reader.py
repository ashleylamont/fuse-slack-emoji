import pytest

from slack_emoji_fs.file_system_serialization.format import MAX_DATA_CHUNK_PAYLOAD_SIZE
from slack_emoji_fs.tree_operations.errors import InvalidFileRangeError, IsDirectoryError


def test_list_directory_returns_only_stored_names(sample_tree) -> None:
    """Directory listing returns stored child names without synthetic dot entries."""
    assert sample_tree.reader.list_directory("/") == ("documents", "blob")
    assert sample_tree.reader.list_directory("/documents") == ("readme.txt",)


def test_read_file_supports_full_and_bounded_reads(sample_tree) -> None:
    """File reads support complete content, byte ranges, and zero-length reads."""
    assert sample_tree.reader.read_file("/documents/readme.txt") == b"read me\n"
    assert sample_tree.reader.read_file("/documents/readme.txt", offset=2, size=4) == b"ad m"
    assert sample_tree.reader.read_file("/documents/readme.txt", size=0) == b""


def test_read_file_across_a_chunk_boundary(sample_tree) -> None:
    """A bounded read can span adjacent stored data chunks."""
    assert sample_tree.reader.read_file(
        "/blob", offset=MAX_DATA_CHUNK_PAYLOAD_SIZE - 2, size=5
    ) == b"aabcd"


def test_read_file_rejects_invalid_ranges_and_directories(sample_tree) -> None:
    """Reads reject negative ranges and attempts to read a directory as a file."""
    with pytest.raises(InvalidFileRangeError):
        sample_tree.reader.read_file("/blob", offset=-1)
    with pytest.raises(InvalidFileRangeError):
        sample_tree.reader.read_file("/blob", size=-1)
    with pytest.raises(IsDirectoryError):
        sample_tree.reader.read_file("/documents")


def test_read_file_honours_logical_eof_when_the_final_chunk_has_extra_bytes(sample_tree) -> None:
    """Logical file size limits reads even when the final stored chunk is longer."""
    chunk_id = sample_tree.repository.store_and_split_data_chunks(b"abcdef")[0]
    # The reader operates on a resolved inode, so this isolates the logical-size invariant.
    from slack_emoji_fs.file_system_models.file_inode import FileInodeObject

    inode = FileInodeObject(
        chunks=[chunk_id], size=3, mode=0o644, uid=1000, gid=1000, mtime=1, ctime=1
    )

    assert sample_tree.reader.read_file_inode(inode, offset=3) == b""
