import logging
import os
import signal

import fuse
from dotenv import load_dotenv
from fuse import Fuse

from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.fuse_adapter.fuse_adapter import FuseAdapter
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.slack_emoji_object_store import SlackEmojiObjectStore
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_writer import TreeWriter

fuse.fuse_python_api = (0, 2)


def init_slack_file_system() -> FileSystem:
    load_dotenv()
    object_store = SlackEmojiObjectStore(os.environ["SLACK_USER_TOKEN"])
    object_repository = ObjectRepository(object_store, namespace="maintest")
    tree_navigator = TreeNavigator(object_repository)
    tree_writer = TreeWriter(object_repository, tree_navigator)
    return FileSystem.create_from_latest_root_or_new(object_repository, tree_navigator, tree_writer)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    usage = """
Userspace Slack Emoji Filesystem

""" + Fuse.fusage
    server = FuseAdapter(
        init_slack_file_system(),
        version="%prog " + fuse.__version__,
        usage=usage,
        dash_s_do="setsingle",
    )
    server.parse(errex=1)

    old_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        server.main()
    finally:
        signal.signal(signal.SIGINT, old_sigint)


if __name__ == "__main__":
    main()
