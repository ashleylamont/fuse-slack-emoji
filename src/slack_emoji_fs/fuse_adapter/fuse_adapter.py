import errno
import os
import stat
from dataclasses import dataclass
from typing import Iterable

from slack_emoji_fs.file_system_models.directory_inode import DirectoryInodeObject
from slack_emoji_fs.file_system_models.file_inode import FileInodeObject
from fuse import Fuse, Direntry, Stat
from slack_emoji_fs.fuse_adapter.errors import translate_fuse_errors
from slack_emoji_fs.fuse_adapter.fuse_operations import FuseStatus
from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.fuse_adapter.fuse_operations import FuseOperations
from typing_extensions import override


def inode_to_fuse_stat(inode_object: object) -> Stat:
    file_type = (
        stat.S_IFREG if isinstance(inode_object, FileInodeObject) else stat.S_IFDIR
    )

    if not isinstance(inode_object, (FileInodeObject, DirectoryInodeObject)):
        raise OSError(errno.EIO, "Unknown inode type", inode_object)

    return Stat(
        st_mode = file_type | (inode_object.mode & 0o7777),
        st_nlink = 1 if isinstance(inode_object, FileInodeObject) else 2,
        st_uid = inode_object.uid,
        st_gid = inode_object.gid,
        st_size = inode_object.size if isinstance(inode_object, FileInodeObject) else 0,
        st_mtime = inode_object.mtime,
        st_ctime = inode_object.ctime,
        st_atime = inode_object.mtime
    )

def validate_open_flags(flags: int) -> int:
    if flags < 0:
        raise OSError(errno.EINVAL, "Invalid open flags")

    access_mode = flags & os.O_ACCMODE
    if access_mode not in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
        raise OSError(errno.EINVAL, "Invalid access mode")

    unsupported_single_bits = (
            getattr(os, "O_DIRECT", 0)
            | getattr(os, "O_PATH", 0)
    )
    if flags & unsupported_single_bits:
        raise OSError(errno.EOPNOTSUPP, "Unsupported open flags")

    o_tmpfile = getattr(os, "O_TMPFILE", 0)
    if o_tmpfile and flags & o_tmpfile == o_tmpfile:
        raise OSError(errno.EOPNOTSUPP, "O_TMPFILE is unsupported")

    return access_mode


@dataclass
class _BufferedFile:
    contents: bytearray
    dirty: bool = False


class FuseAdapter(Fuse, FuseOperations):
    def __init__(
            self,
            file_system: FileSystem,
            *fuse_args: object,
            buffer_writes: bool = False,
            **fuse_kwargs: object,
    ) -> None:
        super().__init__(*fuse_args, **fuse_kwargs)
        self._file_system = file_system
        self._buffer_writes = buffer_writes
        self._write_buffers: dict[str, _BufferedFile] = {}

    def _start_write_buffer(
            self,
            path: str,
            inode: FileInodeObject,
            *,
            truncate: bool = False,
    ) -> _BufferedFile:
        buffered_file = self._write_buffers.get(path)
        if buffered_file is not None:
            if truncate:
                buffered_file.contents.clear()
                buffered_file.dirty = True
            return buffered_file

        contents = bytearray()
        if not truncate:
            contents.extend(
                self._file_system.read_file(path, offset=0, size=inode.size)
            )
        buffered_file = _BufferedFile(contents, dirty=truncate)
        self._write_buffers[path] = buffered_file
        return buffered_file

    def _write_buffer(self, path: str) -> _BufferedFile:
        buffered_file = self._write_buffers.get(path)
        if buffered_file is not None:
            return buffered_file

        resolved = self._file_system.resolve(path)
        inode = resolved.inode_object
        if not isinstance(inode, FileInodeObject):
            raise OSError(errno.EISDIR, "Cannot buffer writes to a directory", path)
        return self._start_write_buffer(path, inode)

    def _flush_write_buffer(self, path: str) -> None:
        buffered_file = self._write_buffers.get(path)
        if buffered_file is None or not buffered_file.dirty:
            return
        self._file_system.replace_file(path, bytes(buffered_file.contents))
        buffered_file.dirty = False

    @override
    @translate_fuse_errors()
    def getattr(self, path: str) -> Stat | int:
        resolved_inode = self._file_system.resolve(path)
        result = inode_to_fuse_stat(resolved_inode.inode_object)
        buffered_file = self._write_buffers.get(path)
        if buffered_file is not None:
            result.st_size = len(buffered_file.contents)
        return result


    @override
    @translate_fuse_errors()
    def readdir(self, path: str, offset: int) -> Iterable[Direntry]:
        return tuple(
            Direntry(name)
            for name in (".", "..", *self._file_system.list_directory(path))
        )

    @override
    @translate_fuse_errors()
    def open(self, path: str, flags: int) -> FuseStatus:
        # Flags are for nerds who implement handles, and a nerd I may be but I'm still not implementing handles in slack emojis
        # so how's about we just agree to validate that the flags *make sense* and call it a day
        validate_open_flags(flags)

        resolved = self._file_system.resolve(path)
        inode = resolved.inode_object

        if isinstance(inode, DirectoryInodeObject):
            raise OSError(errno.EISDIR, "Cannot open a directory as a file", path)

        if not isinstance(inode, FileInodeObject):
            raise OSError(errno.EIO, "Unknown inode type", path)

        if flags & getattr(os, "O_DIRECTORY", 0):
            raise OSError(errno.ENOTDIR, "File is not a directory", path)

        if self._buffer_writes and (flags & os.O_ACCMODE) != os.O_RDONLY:
            self._start_write_buffer(
                path,
                inode,
                truncate=bool(flags & os.O_TRUNC),
            )

        return 0

    @override
    @translate_fuse_errors()
    def create(self, path: str, flags: int, mode: int) -> FuseStatus:
        validate_open_flags(flags)

        context = self.GetContext()
        self._file_system.create_file(
            path,
            mode=mode & 0o7777,
            uid=context["uid"],
            gid=context["gid"],
        )
        if self._buffer_writes:
            self._write_buffers[path] = _BufferedFile(bytearray())

        return 0

    @override
    @translate_fuse_errors()
    def read(self, path: str, size: int, offset: int) -> bytes | int:
        buffered_file = self._write_buffers.get(path)
        if buffered_file is not None:
            if size < 0 or offset < 0:
                raise OSError(errno.EINVAL, "Invalid read range", path)
            return bytes(buffered_file.contents[offset:offset + size])
        return self._file_system.read_file(path, size=size, offset=offset)

    @override
    @translate_fuse_errors()
    def write(self, path: str, buffer: bytes, offset: int) -> int:
        if self._buffer_writes:
            if offset < 0:
                raise OSError(errno.EINVAL, "Cannot write to a negative offset", path)
            buffered_file = self._write_buffer(path)
            if offset > len(buffered_file.contents):
                buffered_file.contents.extend(
                    b"\0" * (offset - len(buffered_file.contents))
                )
            end = offset + len(buffer)
            buffered_file.contents[offset:end] = buffer
            buffered_file.dirty = True
            return len(buffer)
        self._file_system.write_file(path, buffer, offset=offset)
        return len(buffer)

    @override
    @translate_fuse_errors()
    def truncate(self, path: str, length: int) -> FuseStatus:
        if self._buffer_writes and path in self._write_buffers:
            if length < 0:
                raise OSError(errno.EINVAL, "Cannot truncate to a negative size", path)
            buffered_file = self._write_buffers[path]
            if length < len(buffered_file.contents):
                del buffered_file.contents[length:]
            elif length > len(buffered_file.contents):
                buffered_file.contents.extend(
                    b"\0" * (length - len(buffered_file.contents))
                )
            buffered_file.dirty = True
            return 0
        self._file_system.truncate_file(path, length)
        return 0

    @override
    @translate_fuse_errors()
    def flush(self, path: str) -> FuseStatus:
        self._flush_write_buffer(path)
        return 0

    @override
    @translate_fuse_errors()
    def fsync(self, path: str, is_fsync_file: bool) -> FuseStatus:
        self._flush_write_buffer(path)
        return 0

    @override
    @translate_fuse_errors()
    def release(self, path: str, flags: int) -> FuseStatus:
        self._flush_write_buffer(path)
        self._write_buffers.pop(path, None)
        return 0

    @override
    @translate_fuse_errors()
    def mkdir(self, path: str, mode: int) -> FuseStatus:
        context = self.GetContext()
        self._file_system.create_directory(
            path,
            mode=mode & 0o7777,
            uid=context["uid"],
            gid=context["gid"],
        )
        return 0

    @override
    @translate_fuse_errors()
    def unlink(self, path: str) -> FuseStatus:
        self._flush_write_buffer(path)
        self._file_system.unlink_file(path)
        self._write_buffers.pop(path, None)
        return 0

    @override
    @translate_fuse_errors(root_operation_errno=errno.EBUSY)
    def rmdir(self, path: str) -> FuseStatus:
        self._file_system.remove_directory(path)
        return 0

    @override
    @translate_fuse_errors(root_operation_errno=errno.EBUSY)
    def rename(self, source: str, destination: str) -> FuseStatus:
        self._flush_write_buffer(source)
        self._flush_write_buffer(destination)
        self._file_system.rename(source, destination, replace=True)
        self._write_buffers.pop(source, None)
        self._write_buffers.pop(destination, None)
        return 0

    @override
    @translate_fuse_errors()
    def chmod(self, path: str, mode: int) -> FuseStatus:
        self._flush_write_buffer(path)
        self._file_system.chmod(path, mode & 0o7777)
        return 0
