from file_system.fs_operations import SlackBasedFileSystem
from object_store.local_file_object_store import LocalFileObjectStore


def main():
    local_file_object_store = LocalFileObjectStore()
    slack_fs = SlackBasedFileSystem(local_file_object_store)

    slack_fs.mkdir("/test")
    print(slack_fs.read_dir("/"))
    slack_fs.mkdir("/test/foo")
    slack_fs.mkdir("/test/bar")
    print(slack_fs.read_dir("/test"))


if __name__ == '__main__':
    main()