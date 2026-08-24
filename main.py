import logging
import os
import signal
import sys

import fuse
from dotenv import load_dotenv
from fuse import Fuse

from slack_emoji_fs.file_system.file_system import FileSystem
from slack_emoji_fs.cli import parse_application_args
from slack_emoji_fs.fuse_adapter.fuse_adapter import FuseAdapter
from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.slack_emoji_object_store import SlackEmojiObjectStore
from slack_emoji_fs.tree_operations.tree_navigator import TreeNavigator
from slack_emoji_fs.tree_operations.tree_writer import TreeWriter

fuse.fuse_python_api = (0, 2)


def init_slack_file_system(namespace: str = "maintest") -> FileSystem:
    load_dotenv()
    object_store = SlackEmojiObjectStore(os.environ["SLACK_USER_TOKEN"])
    object_repository = ObjectRepository(object_store, namespace=namespace)
    tree_navigator = TreeNavigator(object_repository)
    tree_writer = TreeWriter(object_repository, tree_navigator)
    return FileSystem.create_from_latest_root_or_new(object_repository, tree_navigator, tree_writer)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application_args, fuse_args = parse_application_args(sys.argv[1:])
    usage = """
Userspace Slack Emoji Filesystem

Application options:
  --namespace NAME       alphabetic object ID namespace (default: maintest)
  --buffer-writes        publish file contents on flush (requires -s)

""" + Fuse.fusage
    server = FuseAdapter(
        init_slack_file_system(application_args.namespace),
        buffer_writes=application_args.buffer_writes,
        version="%prog " + fuse.__version__,
        usage=usage,
        dash_s_do="setsingle",
    )
    server.parse(args=fuse_args, errex=1)
    if application_args.buffer_writes and server.multithreaded:
        raise SystemExit("--buffer-writes currently requires the FUSE -s option")
    if application_args.buffer_writes:
        logging.getLogger(__name__).warning(
            "Buffered writes enabled: dirty file contents publish on flush"
        )

    old_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        server.main()
    finally:
        signal.signal(signal.SIGINT, old_sigint)


if __name__ == "__main__":
    main()
