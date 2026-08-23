import inspect
import math
from functools import wraps
from typing import Tuple, List

from slack_emoji_fs.file_system.fs_object import *
from slack_emoji_fs.object_store.object_store import ObjectStore


def with_default_root_inode():
    def decorator(fn):
        sig = inspect.signature(fn)
        last_param = list(sig.parameters.values())[-1]

        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            bound = sig.bind_partial(self, *args, **kwargs)

            if last_param.name not in bound.arguments or bound.arguments[last_param.name] is None:
                latest_root = self.load_latest_root()
                if latest_root is None:
                    raise FileNotFoundError("No root object found in the filesystem")
                root_inode = self.load_inode(latest_root.root_inode_id)
                if not isinstance(root_inode, DirectoryInodeObject):
                    raise ValueError("Root inode is not a directory")
                bound.arguments[last_param.name] = root_inode

            return fn(*bound.args, **bound.kwargs)

        return wrapper

    return decorator

class SlackBasedFileSystem:
    object_store: ObjectStore

    def __init__(self, slack_interface: ObjectStore):
        self.object_store = slack_interface

    def list_roots(self) -> list[str]:
        """List all root object IDs in the storage backend, in descending chronological order."""
        all_emojis = self.object_store.list_ids()
        root_ids = [name for name in all_emojis if name.startswith("efs_rot_")]
        # Root IDs are named efs_root_<timestamp>_<random>, so sorting them in descending order
        # will give us the most recent roots first.
        root_ids.sort(reverse=True)
        return root_ids


    @with_default_root_inode()
    def resolve_path_directory(
            self,
            path: str,
            root_inode: DirectoryInodeObject | None = None
    ) -> Tuple[DirectoryInodeObject, str]:
        """Resolve a filesystem path to its parent directory, and the name of the object in that directory."""
        # We're not handling relative paths or special components like '.' or '..' for simplicity (could be added later)
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot find parent directory of root path")
        *path_parts, last_part = [part for part in path.split("/") if part]

        current_inode = root_inode
        for part in path_parts:
            if not isinstance(current_inode, DirectoryInodeObject):
                raise FileNotFoundError(f"Path component '{part}' is not a directory")
            dir_entry = self.load_directory_entry(current_inode.dir_object_id)
            if part not in dir_entry.entries:
                raise FileNotFoundError(f"Path component '{part}' not found")
            next_inode_id = dir_entry.entries[part]
            current_inode = self.load_inode(next_inode_id)

        if not isinstance(current_inode, DirectoryInodeObject):
            raise FileNotFoundError(f"Path component '{path_parts[-1]}' is not a directory")
        return current_inode, last_part

    @with_default_root_inode()
    def resolve_path(
            self,
            path: str,
            root_inode: DirectoryInodeObject | None = None
    ) -> FileInodeObject | DirectoryInodeObject:
        """Resolve a filesystem path to its corresponding inode object."""
        # We're not handling relative paths or special components like '.' or '..' for simplicity (could be added later)
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        path_parts = [part for part in path.split("/") if part]

        current_inode = root_inode
        for part in path_parts:
            if not isinstance(current_inode, DirectoryInodeObject):
                raise FileNotFoundError(f"Path component '{part}' is not a directory")
            dir_entry = self.load_directory_entry(current_inode.dir_object_id)
            if part not in dir_entry.entries:
                raise FileNotFoundError(f"Path component '{part}' not found")
            next_inode_id = dir_entry.entries[part]
            current_inode = self.load_inode(next_inode_id)

        return current_inode

    @with_default_root_inode()
    def resolve_full_path(
            self,
            path: str,
            root_inode: DirectoryInodeObject | None = None
    ) -> List[Tuple[DirectoryInodeObject, DirectoryEntryObject, str, InodeObject]]:
        """Resolve the full chain of nodes in a path."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        path_parts = [part for part in path.split("/") if part]

        path_chain: List[Tuple[DirectoryInodeObject, DirectoryEntryObject, str, InodeObject]] = []

        current_inode = root_inode
        for part in path_parts:
            if not isinstance(current_inode, DirectoryInodeObject):
                raise FileNotFoundError(f"Path component '{part}' is not a directory")
            dir_entry = self.load_directory_entry(current_inode.dir_object_id)
            if part not in dir_entry.entries:
                raise FileNotFoundError(f"Path component '{part}' not found")
            next_inode_id = dir_entry.entries[part]
            next_inode = self.load_inode(next_inode_id)
            path_chain.append((
                current_inode, dir_entry, part, next_inode
            ))

        return path_chain

    def get_attr(
            self,
            path: str,
            root_id: str | None = None
    ) -> Stat:
        """Resolve an inode by path and return the stat-like objects for it."""
        # We need the actual root inode ID rather than just the inode object, so we need to directly fetch it instead of relying on with_default_root_inode
        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                # We could just fail here but actually that's a really bad idea so let's just quietly make an empty root dir instead of failing
                # raise FileNotFoundError("No file system root has been created yet.")
                new_root_dir_entry = DirectoryEntryObject(entries={})
                new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
                new_root_inode = DirectoryInodeObject(
                    mode=0o755, # todo: change this probs
                    uid=1000,
                    gid=1000,
                    mtime=int(time.time()),
                    ctime=int(time.time()),
                    dir_object_id=new_root_dir_entry_id
                )
                new_root_inode_id = self.store_fs_object(new_root_inode)
                new_root = RootObject(
                    parent_root_id=None,
                    root_inode_id=new_root_inode_id
                )
                root_id = self.store_fs_object(new_root)
                # wow this is so janky lol
                # we need to refresh the emoji cache after making new ones, so we do that here
                self.list_roots()
            else:
                root_id = root_list[0]
        root_node = self.load_root(root_id)
        root_inode_id = root_node.root_inode_id
        root_inode = self.load_inode(root_inode_id)

        if path == "/":
            # We need to handle fetching the root separately as resolve_path_directory won't work
            return inode_to_fuse_stat(root_inode, root_inode_id)


        parent_inode, child_name = self.resolve_path_directory(path, root_inode)
        parent_directory_entry = self.load_directory_entry(parent_inode.dirent_object_id)
        if child_name not in parent_directory_entry.entries:
            raise FileNotFoundError(f"Path component '{path}' not found")
        target_inode_id = parent_directory_entry.entries[child_name]
        target_inode = self.load_inode(target_inode_id)
        return inode_to_fuse_stat(target_inode, target_inode_id)

    @with_default_root_inode()
    def read_dir(
            self,
            path: str,
            root_inode: DirectoryInodeObject | None = None
    ) -> list[str]:
        """Resolve a directory and return its contents."""
        dir_inode = self.resolve_path(path, root_inode)
        dir_entry = self.load_directory_entry(dir_inode.dirent_object_id)
        return [
            ".",
            "..",
            *sorted(dir_entry.entries.keys()),
        ]

    @with_default_root_inode()
    def read_file(
            self,
            path: str,
            offset: int = 0,
            size: int = -1,
            root_inode: DirectoryInodeObject | None = None
    ) -> bytes:
        """Resolve a file object, and retrieve its data from relevant chunks."""
        file_inode = self.resolve_path(path, root_inode)
        if file_inode.inode_type == INODE_TYPE_DIRECTORY:
            raise FileNotFoundError(f"Tried to read file at {path} but a directory was found.")

        file_contents = b""
        starting_chunk = offset // MAX_DATA_CHUNK_PAYLOAD_SIZE
        starting_chunk_offset = offset % MAX_DATA_CHUNK_PAYLOAD_SIZE
        for chunk_index in range(starting_chunk, len(file_inode.chunks)):
            read_next_bytes = MAX_DATA_CHUNK_PAYLOAD_SIZE \
                if size == -1 \
                else size - len(file_contents)
            chunk = self.load_data_chunk(file_inode.chunks[chunk_index])
            chunk_data = chunk.data
            file_contents += chunk_data[starting_chunk_offset:read_next_bytes+starting_chunk_offset] \
                if chunk_index == starting_chunk_offset \
                else chunk_data[:read_next_bytes]
            if len(file_contents) == size:
                break
        return file_contents

    def mkdir(
            self,
            path: str,
            mode: int = 0o755,
            root_id: str | None = None
    ) -> str:
        """Creates a new directory at the given path, and returns the new root inode containing those updates."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot create directory at root path.")

        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                # If we're creating an entirely new root and directory inside it, then we can just handle that here
                path_parts = [path_part for path_part in path.split("/") if path_part]
                if len(path_parts) != 1:
                    raise ValueError("Can only create directories at the root level, when initialising without a root.")
                new_target_dir_entry = DirectoryEntryObject(entries={})
                new_target_dir_entry_id = self.store_fs_object(new_target_dir_entry)
                new_target_inode = DirectoryInodeObject(
                    dir_object_id=new_target_dir_entry_id,
                    mode=mode,
                    uid=1000,
                    gid=1000,
                    mtime=int(time.time()),
                    ctime=int(time.time()),
                )
                new_target_inode_id = self.store_fs_object(new_target_inode)
                new_root_dir_entry = DirectoryEntryObject(
                    entries={
                        path_parts[0]: new_target_inode_id,
                    }
                )
                new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
                new_root_inode = DirectoryInodeObject(
                    dir_object_id=new_root_dir_entry_id,
                    mode=0o755, # should probably change this later
                    uid=1000,
                    gid=1000,
                    mtime=int(time.time()),
                    ctime=int(time.time()),
                )
                new_root_inode_id = self.store_fs_object(new_root_inode)
                new_root_object = RootObject(
                    parent_root_id=None,
                    root_inode_id=new_root_inode_id,
                )
                return self.store_fs_object(new_root_object)
            else:
                root_id = root_list[0]

        root = self.load_root(root_id)
        root_inode = self.load_inode(root.root_inode_id)
        if not isinstance(root_inode, DirectoryInodeObject):
            raise FileNotFoundError("Could not find root inode successfully.")

        *path_parts, final_dir_name = [path_part for path_part in path.split("/") if path_part]
        # Get all inodes and parts that we'll need to update leading up to our new directory
        # Note: the final item in path chain will be the **parent** directory of the directory we're creating in.
        #       i.e. if we create /a/b/c/d, then the chain will be [[a entry], [b entry]] and c will be the referenced child of b
        path_chain = self.resolve_full_path(f"/{"/".join(path_parts)}/", root_inode)
        # If path_chain is empty then we're creating in the root dir
        if not path_chain:
            new_final_dir_entry = DirectoryEntryObject(entries={})
            new_final_dir_entry_id = self.store_fs_object(new_final_dir_entry)
            new_final_dir_inode = DirectoryInodeObject(
                mode=mode,
                uid=1000, # Not used yet
                gid=1000, # Not used yet
                mtime=int(time.time()),
                ctime=int(time.time()),
                dir_object_id=new_final_dir_entry_id
            )
            new_final_dir_inode_id = self.store_fs_object(new_final_dir_inode)
            root_dir_entry = self.load_directory_entry(root_inode.dirent_object_id)
            new_root_dir_entry = DirectoryEntryObject(
                entries={
                    **root_dir_entry.entries,
                    final_dir_name: new_final_dir_inode_id,
                }
            )
            new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
            new_root_inode = root_inode.model_copy()
            new_root_inode.dirent_object_id = new_root_dir_entry_id
            new_root_inode_id = self.store_fs_object(new_root_inode)
            new_root = RootObject(
                parent_root_id=root_id,
                root_inode_id=new_root_inode_id,
            )
            new_root_id = self.store_fs_object(new_root)
            return new_root_id

        final_path_chain_entry = path_chain[-1]
        final_parent_dir_inode = final_path_chain_entry[3]
        if not isinstance(final_parent_dir_inode, DirectoryInodeObject):
            raise FileNotFoundError("Cannot create a directory inside a file.")
        final_parent_dir_entry = self.load_directory_entry(final_parent_dir_inode.dirent_object_id)
        if final_dir_name in final_parent_dir_entry.entries:
            raise NameError(f"File or directory with name \"{final_dir_name}\" already exists at target path.")

        # Ok we've established that we can make those updates, now let's do it.
        # Do it from the leaf up, so that the root is the last change we commit
        new_final_dir_entry = DirectoryEntryObject(
            entries={}
        )
        new_final_dir_entry_id = self.store_fs_object(new_final_dir_entry)
        new_final_dir_inode = DirectoryInodeObject(
            mode=mode,
            uid=1000, # Not used yet
            gid=1000, # Not used yet
            mtime=int(time.time()),
            ctime=int(time.time()),
            dir_object_id=new_final_dir_entry_id
        )
        new_final_dir_inode_id = self.store_fs_object(new_final_dir_inode)

        new_final_parent_dir_entry = DirectoryEntryObject(
            entries={
                **final_parent_dir_entry.entries,
                final_dir_name: new_final_dir_inode_id
            }
        )
        new_final_parent_dir_entry_id = self.store_fs_object(new_final_parent_dir_entry)
        new_final_parent_dir_inode = final_parent_dir_inode.model_copy()
        new_final_parent_dir_inode.dirent_object_id = new_final_parent_dir_entry_id
        new_final_parent_dir_inode_id = self.store_fs_object(new_final_parent_dir_inode)

        last_path_inode_id = new_final_parent_dir_inode_id
        for path_chain_entry_to_update in path_chain[::-1]:
            path_inode, path_dir_entry, path_child_name, path_child_inode = path_chain_entry_to_update
            # For each entry, update the marked child to point to last_path_inode_id, then replace the dir entry and inode
            new_path_dir_entry = path_dir_entry.model_copy()
            new_path_dir_entry.entries[path_child_name] = last_path_inode_id
            new_path_dir_entry_id = self.store_fs_object(new_path_dir_entry)
            new_path_inode = path_inode.model_copy()
            new_path_inode.dirent_object_id = new_path_dir_entry_id
            new_path_inode_id = self.store_fs_object(new_path_inode)
            last_path_inode_id = new_path_inode_id
        # Eventually, last_path_inode_id points to our new root directory inode object
        new_root_inode = RootObject(
            parent_root_id=root_id,
            root_inode_id=last_path_inode_id
        )
        return self.store_fs_object(new_root_inode)

    def create_file(
            self,
            path: str,
            mode: int = 0o755,
            file_contents: bytes = b'',
            root_id: str | None = None
    ) -> str:
        """Creates a new file with the specified contents at the given path, and returns the new root inode containing those updates."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot create file at root path.")

        # Yeah this is kinda inefficient since we're still making the file even if we might not be able to save it, but oh well :shrug:
        file_chunks = []
        for file_chunk_index in range(0, math.ceil(len(file_contents) / MAX_DATA_CHUNK_PAYLOAD_SIZE)):
            file_chunk_payload = file_contents[file_chunk_index * MAX_DATA_CHUNK_PAYLOAD_SIZE:(file_chunk_index + 1) * MAX_DATA_CHUNK_PAYLOAD_SIZE]
            file_chunk = ObjectDataChunk(
                data=file_chunk_payload
            )
            file_chunk_id = self.store_fs_object(file_chunk)
            file_chunks.append(file_chunk_id)
        file_inode = FileInodeObject(
            mode=mode,
            uid=1000,
            gid=1000,
            mtime=int(time.time()),
            ctime=int(time.time()),
            chunks=file_chunks,
            size=len(file_contents)
        )
        file_inode_id = self.store_fs_object(file_inode)

        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                # If we're creating an entirely new root and file inside it, then we can just handle that here.
                path_parts = [path_part for path_part in path.split("/") if path_part]
                if len(path_parts) != 1:
                    raise ValueError("Can only create files at the root level, when initialising without a root.")
                new_root_dir_entry = DirectoryEntryObject(
                    entries={
                        path_parts[0]: file_inode_id
                    }
                )
                new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
                new_root_inode = DirectoryInodeObject(
                    dir_object_id=new_root_dir_entry_id,
                    mode=0o755, # should probably change this later
                    uid=1000,
                    gid=1000,
                    mtime=int(time.time()),
                    ctime=int(time.time()),
                )
                new_root_inode_id = self.store_fs_object(new_root_inode)
                new_root_object = RootObject(
                    parent_root_id=None,
                    root_inode_id=new_root_inode_id,
                )
                return self.store_fs_object(new_root_object)
            else:
                root_id = root_list[0]

        root = self.load_root(root_id)
        root_inode = self.load_inode(root.root_inode_id)
        if not isinstance(root_inode, DirectoryInodeObject):
            raise FileNotFoundError("Could not find root inode successfully.")

        *path_parts, final_file_name = [path_part for path_part in path.split("/") if path_part]
        # Get all inodes and parts that we'll need to update leading up to our new file
        # Note: the final item in path chain will be the **parent** directory of the directory we're creating in.
        #       i.e. if we create /a/b/c/d.txt, then the chain will be [[a entry], [b entry]] and c will be the referenced child of b
        path_chain = self.resolve_full_path(f"/{"/".join(path_parts)}/", root_inode)
        # If path_chain is empty then we're creating in the root dir
        if not path_chain:
            root_dir_entry = self.load_directory_entry(root_inode.dirent_object_id)
            new_root_dir_entry = DirectoryEntryObject(
                entries={
                    **root_dir_entry.entries,
                    final_file_name: file_inode_id
                }
            )
            new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
            new_root_inode = root_inode.model_copy()
            new_root_inode.dirent_object_id = new_root_dir_entry_id
            new_root_inode_id = self.store_fs_object(new_root_inode)
            new_root = RootObject(
                parent_root_id=root_id,
                root_inode_id=new_root_inode_id,
            )
            new_root_id = self.store_fs_object(new_root)
            return new_root_id

        final_path_chain_entry = path_chain[-1]
        final_parent_dir_inode = final_path_chain_entry[3]
        if not isinstance(final_parent_dir_inode, DirectoryInodeObject):
            raise FileNotFoundError("Cannot create a directory inside a file.")
        final_parent_dir_entry = self.load_directory_entry(final_parent_dir_inode.dirent_object_id)
        if final_file_name in final_parent_dir_entry.entries:
            raise NameError(f"File or directory with name \"{final_file_name}\" already exists at target path.")

        # Ok we've established that we can make those updates, now let's do it.
        # Do it from the leaf up, so that the root is the last change we commit
        new_final_parent_dir_entry = DirectoryEntryObject(
            entries={
                **final_parent_dir_entry.entries,
                final_file_name: file_inode_id
            }
        )
        new_final_parent_dir_entry_id = self.store_fs_object(new_final_parent_dir_entry)
        new_final_parent_dir_inode = final_parent_dir_inode.model_copy()
        new_final_parent_dir_inode.dirent_object_id = new_final_parent_dir_entry_id
        new_final_parent_dir_inode_id = self.store_fs_object(new_final_parent_dir_inode)

        last_path_inode_id = new_final_parent_dir_inode_id
        for path_chain_entry_to_update in path_chain[::-1]:
            path_inode, path_dir_entry, path_child_name, path_child_inode = path_chain_entry_to_update
            # For each entry, update the marked child to point to last_path_inode_id, then replace the dir entry and inode
            new_path_dir_entry = path_dir_entry.model_copy()
            new_path_dir_entry.entries[path_child_name] = last_path_inode_id
            new_path_dir_entry_id = self.store_fs_object(new_path_dir_entry)
            new_path_inode = path_inode.model_copy()
            new_path_inode.dirent_object_id = new_path_dir_entry_id
            new_path_inode_id = self.store_fs_object(new_path_inode)
            last_path_inode_id = new_path_inode_id
        # Eventually, last_path_inode_id points to our new root directory inode object
        new_root_inode = RootObject(
            parent_root_id=root_id,
            root_inode_id=last_path_inode_id
        )
        return self.store_fs_object(new_root_inode)

    def unlink(
            self,
            path: str,
            root_id: str | None = None
    ) -> str:
        """Unlinks a file at a given path."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot unlink root path.")

        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                # If we have no root then there's nothing to unlink
                raise FileNotFoundError("Tried to unlink a file but no root was found.")
            else:
                root_id = root_list[0]

        root = self.load_root(root_id)
        root_inode = self.load_inode(root.root_inode_id)
        if not isinstance(root_inode, DirectoryInodeObject):
            raise FileNotFoundError("Could not find root inode successfully.")

        *path_parts, final_file_name = [path_part for path_part in path.split("/") if path_part]
        # Get all inodes and parts that we'll need to update leading up to our unlinked file
        # Note: the final item in path chain will be the **parent** directory of the directory we're deleting in.
        #       i.e. if we create /a/b/c/d.txt, then the chain will be [[a entry], [b entry]] and c will be the referenced child of b
        path_chain = self.resolve_full_path(f"/{"/".join(path_parts)}/", root_inode)
        final_path_chain_entry = path_chain[-1]
        final_parent_dir_inode = final_path_chain_entry[3]
        if not isinstance(final_parent_dir_inode, DirectoryInodeObject):
            raise FileNotFoundError("Cannot create a directory inside a file.")
        final_parent_dir_entry = self.load_directory_entry(final_parent_dir_inode.dirent_object_id)
        if not final_file_name in final_parent_dir_entry.entries:
            raise NameError(f"No file with name \"{final_file_name}\" exists at target path.")

        final_file_inode = self.load_inode(final_parent_dir_entry.entries[final_file_name])
        if isinstance(final_file_inode, DirectoryInodeObject):
            raise FileNotFoundError("Tried to unlink a directory. Use rmdir instead.")

        # Ok we've established that we can make those updates, now let's do it.
        # Do it from the leaf up, so that the root is the last change we commit
        new_final_parent_dir_entry = DirectoryEntryObject(
            entries={
                dir_entry_name: inode_id
                    for dir_entry_name, inode_id
                    in final_parent_dir_entry.entries.items()
                        if dir_entry_name != final_file_name
            }
        )
        new_final_parent_dir_entry_id = self.store_fs_object(new_final_parent_dir_entry)
        new_final_parent_dir_inode = final_parent_dir_inode.model_copy()
        new_final_parent_dir_inode.dirent_object_id = new_final_parent_dir_entry_id
        new_final_parent_dir_inode_id = self.store_fs_object(new_final_parent_dir_inode)

        last_path_inode_id = new_final_parent_dir_inode_id
        for path_chain_entry_to_update in path_chain[::-1]:
            path_inode, path_dir_entry, path_child_name, path_child_inode = path_chain_entry_to_update
            # For each entry, update the marked child to point to last_path_inode_id, then replace the dir entry and inode
            new_path_dir_entry = path_dir_entry.model_copy()
            new_path_dir_entry.entries[path_child_name] = last_path_inode_id
            new_path_dir_entry_id = self.store_fs_object(new_path_dir_entry)
            new_path_inode = path_inode.model_copy()
            new_path_inode.dirent_object_id = new_path_dir_entry_id
            new_path_inode_id = self.store_fs_object(new_path_inode)
            last_path_inode_id = new_path_inode_id
        # Eventually, last_path_inode_id points to our new root directory inode object
        new_root_inode = RootObject(
            parent_root_id=root_id,
            root_inode_id=last_path_inode_id
        )
        return self.store_fs_object(new_root_inode)

    def rmdir(
            self,
            path: str,
            root_id: str | None = None
    ) -> str:
        """Removes a directory at a given path."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot unlink root path.")

        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                # If we have no root then there's nothing to unlink
                raise FileNotFoundError("Tried to unlink a file but no root was found.")
            else:
                root_id = root_list[0]

        root = self.load_root(root_id)
        root_inode = self.load_inode(root.root_inode_id)
        if not isinstance(root_inode, DirectoryInodeObject):
            raise FileNotFoundError("Could not find root inode successfully.")

        *path_parts, final_file_name = [path_part for path_part in path.split("/") if path_part]
        # Get all inodes and parts that we'll need to update leading up to our removed directory
        # Note: the final item in path chain will be the **parent** directory of the directory we're deleting in.
        #       i.e. if we remove /a/b/c/d/, then the chain will be [[a entry], [b entry]] and c will be the referenced child of b
        path_chain = self.resolve_full_path(f"/{"/".join(path_parts)}/", root_inode)
        final_path_chain_entry = path_chain[-1]
        final_parent_dir_inode = final_path_chain_entry[3]
        if not isinstance(final_parent_dir_inode, DirectoryInodeObject):
            raise FileNotFoundError("Cannot create a directory inside a file.")
        final_parent_dir_entry = self.load_directory_entry(final_parent_dir_inode.dirent_object_id)
        if not final_file_name in final_parent_dir_entry.entries:
            raise NameError(f"No file with name \"{final_file_name}\" exists at target path.")

        final_dir_inode = self.load_inode(final_parent_dir_entry.entries[final_file_name])
        if isinstance(final_dir_inode, FileInodeObject):
            raise FileNotFoundError("Tried to do rmdir on a file. Use unlink instead.")

        file_dir_dir_entry = self.load_directory_entry(final_dir_inode.dirent_object_id)
        if len(file_dir_dir_entry.entries) > 0:
            raise ValueError("Tried to use rmdir on a non-empty directory.")

        # Ok we've established that we can make those updates, now let's do it.
        # Do it from the leaf up, so that the root is the last change we commit
        new_final_parent_dir_entry = DirectoryEntryObject(
            entries={
                dir_entry_name: inode_id
                    for dir_entry_name, inode_id
                    in final_parent_dir_entry.entries.items()
                        if dir_entry_name != final_file_name
            }
        )
        new_final_parent_dir_entry_id = self.store_fs_object(new_final_parent_dir_entry)
        new_final_parent_dir_inode = final_parent_dir_inode.model_copy()
        new_final_parent_dir_inode.dirent_object_id = new_final_parent_dir_entry_id
        new_final_parent_dir_inode_id = self.store_fs_object(new_final_parent_dir_inode)

        last_path_inode_id = new_final_parent_dir_inode_id
        for path_chain_entry_to_update in path_chain[::-1]:
            path_inode, path_dir_entry, path_child_name, path_child_inode = path_chain_entry_to_update
            # For each entry, update the marked child to point to last_path_inode_id, then replace the dir entry and inode
            new_path_dir_entry = path_dir_entry.model_copy()
            new_path_dir_entry.entries[path_child_name] = last_path_inode_id
            new_path_dir_entry_id = self.store_fs_object(new_path_dir_entry)
            new_path_inode = path_inode.model_copy()
            new_path_inode.dirent_object_id = new_path_dir_entry_id
            new_path_inode_id = self.store_fs_object(new_path_inode)
            last_path_inode_id = new_path_inode_id
        # Eventually, last_path_inode_id points to our new root directory inode object
        new_root_inode = RootObject(
            parent_root_id=root_id,
            root_inode_id=last_path_inode_id
        )
        return self.store_fs_object(new_root_inode)

    def write_file(
            self,
            path: str,
            buffer: bytes = b'',
            offset: int = 0,
            root_id: str | None = None
    ) -> str:
        """Writes to a file, overwriting the file contents from offset."""
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if path == "/":
            raise ValueError("Cannot write file at root path.")

        if root_id is None:
            root_list = self.list_roots()
            if not root_list:
                raise FileNotFoundError("Cannot write to a file without a root.")
            else:
                root_id = root_list[0]

        root = self.load_root(root_id)
        root_inode = self.load_inode(root.root_inode_id)
        if not isinstance(root_inode, DirectoryInodeObject):
            raise FileNotFoundError("Could not find root inode successfully.")

        existing_file_contents = self.read_file(path, 0, -1, root_inode) # This could be made more efficient using our offset for large files
        new_file_contents = existing_file_contents[:offset] + buffer + existing_file_contents[offset+len(buffer):]
        file_chunks = []
        for file_chunk_index in range(0, math.ceil(len(new_file_contents) / MAX_DATA_CHUNK_PAYLOAD_SIZE)):
            file_chunk_payload = new_file_contents[file_chunk_index * MAX_DATA_CHUNK_PAYLOAD_SIZE:(file_chunk_index + 1) * MAX_DATA_CHUNK_PAYLOAD_SIZE]
            file_chunk = ObjectDataChunk(
                data=file_chunk_payload
            )
            file_chunk_id = self.store_fs_object(file_chunk)
            file_chunks.append(file_chunk_id)
        existing_file_inode = self.resolve_path(path, root_inode) # wow this is really inefficient
        new_file_inode = existing_file_inode.model_copy()
        new_file_inode.mtime = int(time.time())
        new_file_inode.chunks=file_chunks
        new_file_inode_id = self.store_fs_object(new_file_inode)

        *path_parts, final_file_name = [path_part for path_part in path.split("/") if path_part]
        # Get all inodes and parts that we'll need to update leading up to our new file
        # Note: the final item in path chain will be the **parent** directory of the directory we're creating in.
        #       i.e. if we create /a/b/c/d.txt, then the chain will be [[a entry], [b entry]] and c will be the referenced child of b
        path_chain = self.resolve_full_path(f"/{"/".join(path_parts)}/", root_inode)
        # If path_chain is empty then we're creating in the root dir
        if not path_chain:
            root_dir_entry = self.load_directory_entry(root_inode.dirent_object_id)
            new_root_dir_entry = root_dir_entry.model_copy()
            new_root_dir_entry.entries[final_file_name] = new_file_inode_id
            new_root_dir_entry_id = self.store_fs_object(new_root_dir_entry)
            new_root_inode = root_inode.model_copy()
            new_root_inode.dirent_object_id = new_root_dir_entry_id
            new_root_inode_id = self.store_fs_object(new_root_inode)
            new_root = RootObject(
                parent_root_id=root_id,
                root_inode_id=new_root_inode_id,
            )
            new_root_id = self.store_fs_object(new_root)
            return new_root_id

        final_path_chain_entry = path_chain[-1]
        final_parent_dir_inode = final_path_chain_entry[3]
        if not isinstance(final_parent_dir_inode, DirectoryInodeObject):
            raise FileNotFoundError("Cannot edit a file inside a file.")
        final_parent_dir_entry = self.load_directory_entry(final_parent_dir_inode.dirent_object_id)
        if final_file_name in final_parent_dir_entry.entries:
            raise NameError(f"File or directory with name \"{final_file_name}\" already exists at target path.")

        # Ok we've established that we can make those updates, now let's do it.
        # Do it from the leaf up, so that the root is the last change we commit
        new_final_parent_dir_entry = DirectoryEntryObject(
            entries={
                **final_parent_dir_entry.entries,
                final_file_name: new_file_inode_id
            }
        )
        new_final_parent_dir_entry_id = self.store_fs_object(new_final_parent_dir_entry)
        new_final_parent_dir_inode = final_parent_dir_inode.model_copy()
        new_final_parent_dir_inode.dirent_object_id = new_final_parent_dir_entry_id
        new_final_parent_dir_inode_id = self.store_fs_object(new_final_parent_dir_inode)

        last_path_inode_id = new_final_parent_dir_inode_id
        for path_chain_entry_to_update in path_chain[::-1]:
            path_inode, path_dir_entry, path_child_name, path_child_inode = path_chain_entry_to_update
            # For each entry, update the marked child to point to last_path_inode_id, then replace the dir entry and inode
            new_path_dir_entry = path_dir_entry.model_copy()
            new_path_dir_entry.entries[path_child_name] = last_path_inode_id
            new_path_dir_entry_id = self.store_fs_object(new_path_dir_entry)
            new_path_inode = path_inode.model_copy()
            new_path_inode.dirent_object_id = new_path_dir_entry_id
            new_path_inode_id = self.store_fs_object(new_path_inode)
            last_path_inode_id = new_path_inode_id
        # Eventually, last_path_inode_id points to our new root directory inode object
        new_root_inode = RootObject(
            parent_root_id=root_id,
            root_inode_id=last_path_inode_id
        )
        return self.store_fs_object(new_root_inode)