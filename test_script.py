from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.local_file_object_store import LocalFileObjectStore
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_writer import TreeWriter


def main():
    local_file_object_store = LocalFileObjectStore()
    object_repository = ObjectRepository(local_file_object_store, namespace="testscript")
    tree_navigator = TreeNavigator(object_repository)
    tree_writer = TreeWriter(object_repository, tree_navigator)
    file_system = FileSystem.create_from_latest_root_or_new(object_repository, tree_navigator, tree_writer)

    file_system.create_directory("/test", mode=0o777, uid=0, gid=0)
    print(file_system.list_directory("/"))
    file_system.create_file("/test/foo", mode=0o777, uid=0, gid=0, contents=b"foo")
    file_system.create_file("/test/bar", mode=0o777, uid=0, gid=0, contents=b"bar")
    print(file_system.list_directory("/test"))


if __name__ == '__main__':
    main()