class FileSystemError(Exception):
    pass

class InvalidPathError(FileSystemError):
    """
    Malformed, relative, unsupported, or otherwise invalid path syntax.
    """
    pass

class PathNotFoundError(FileSystemError):
    """
    A requested name is absent from its resolved parent.
    """
    pass

class NotDirectoryError(FileSystemError):
    """
    Traversal or directory operation encountered a file when it expected a directory.
    """
    pass

class IsDirectoryError(FileSystemError):
    """"
    A file-only operation encountered a directory when it expected a file.
    """
    pass

class EntryExistsError(FileSystemError):
    """
    Creation or non-replacing rename found an existing entry in the tree at the target name.
    """
    pass

class DirectoryNotEmptyError(FileSystemError):
    """
    Removal/replacement requires an empty directory.
    """
    pass

class RootOperationError(FileSystemError):
    """
    An operation requires a parent entry but targets '/'.
    """
    pass

class InvalidFileRangeError(FileSystemError):
    """
    A negative or otherwise unsupported offset/size.
    """
    pass

class CorruptTreeError(FileSystemError):
    """
    An object graph violates an internal invariant or a referenced object has the wrong semantic role.
    """
    pass