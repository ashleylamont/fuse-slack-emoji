from file_system.fs_operations import SlackBasedFileSystem
from storage_backend.slack_mock import SlackMockInterface

def main():
    slack_mock = SlackMockInterface()
    slack_fs = SlackBasedFileSystem(slack_mock)

    slack_fs.mkdir("/test")
    print(slack_fs.read_dir("/"))
    slack_fs.mkdir("/test/foo")
    slack_fs.mkdir("/test/bar")
    print(slack_fs.read_dir("/test"))


if __name__ == '__main__':
    main()