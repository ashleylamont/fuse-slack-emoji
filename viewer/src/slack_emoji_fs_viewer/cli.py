"""Command-line entry point for the history viewer."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from slack_emoji_fs.object_repository.object_repository import ObjectRepository
from slack_emoji_fs.object_store.local_file_object_store import LocalFileObjectStore
from slack_emoji_fs.object_store.slack_emoji_object_store import SlackEmojiObjectStore

from .history import HistoryViewer
from .web import serve


class ReadOnlyPNGDirectoryStore(LocalFileObjectStore):
    """Open an existing directory written by ``LocalFileObjectStore``."""

    def __init__(self, directory: Path) -> None:
        resolved = directory.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Object-store directory does not exist: {resolved}")
        # LocalFileObjectStore normally creates a temporary directory. Pointing
        # directly at an existing directory avoids that side effect.
        self.tmpdir = str(resolved)

    def get(self, object_id: str) -> bytes | None:
        if Path(object_id).name != object_id:
            return None
        return super().get(object_id)

    def put(self, object_id: str, object_data: bytes) -> None:
        raise PermissionError("The history viewer opens local object stores read-only")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse Slack Emoji FS roots, trees, and history")
    parser.add_argument("--namespace", default="maintest", help="repository namespace (letters only)")
    parser.add_argument("--host", default="127.0.0.1", help="listen address (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8765, help="listen port (default: %(default)s)")
    parser.add_argument("--store", choices=("slack", "local"), default="slack", help="object-store backend")
    parser.add_argument("--directory", type=Path, help="existing LocalFileObjectStore PNG directory")
    parser.add_argument(
        "--slack-token-env",
        default="SLACK_USER_TOKEN",
        metavar="NAME",
        help="environment variable containing the Slack token (default: %(default)s)",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _repository(args: argparse.Namespace) -> ObjectRepository:
    if args.store == "local":
        if args.directory is None:
            raise ValueError("--directory is required with --store local")
        store = ReadOnlyPNGDirectoryStore(args.directory)
    else:
        token = os.environ.get(args.slack_token_env)
        if not token:
            raise ValueError(f"Slack token environment variable {args.slack_token_env!r} is not set")
        store = SlackEmojiObjectStore(token)
    return ObjectRepository(store, args.namespace)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        repository = _repository(args)
    except ValueError as error:
        parser.error(str(error))
    serve(HistoryViewer(repository), args.host, args.port)
    return 0
