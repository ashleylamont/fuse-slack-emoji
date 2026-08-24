"""Application-specific command-line options layered over fuse-python's parser."""

import argparse


def parse_application_args(
        args: list[str],
) -> tuple[argparse.Namespace, list[str]]:
    """Parse application options while leaving mount options for fuse-python."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument(
        "--namespace",
        default="maintest",
        help="alphabetic object ID namespace (default: maintest)",
    )
    parser.add_argument(
        "--buffer-writes",
        action="store_true",
        help="buffer file writes until flush (currently requires -s)",
    )
    parsed, fuse_args = parser.parse_known_args(args)
    if not parsed.namespace.isalpha():
        parser.error("--namespace must contain alphabetic characters only")
    return parsed, fuse_args
