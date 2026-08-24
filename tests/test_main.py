from __future__ import annotations

import pytest

from slack_emoji_fs.cli import parse_application_args


def test_application_options_leave_fuse_arguments_untouched() -> None:
    """Extracts namespace and buffering options without consuming FUSE mount options."""
    parsed, fuse_args = parse_application_args(
        [
            "/tmp/slack-emoji-mount",
            "-d",
            "-s",
            "--namespace",
            "conference",
            "--buffer-writes",
        ]
    )

    assert parsed.namespace == "conference"
    assert parsed.buffer_writes is True
    assert fuse_args == ["/tmp/slack-emoji-mount", "-d", "-s"]


def test_namespace_must_match_repository_constraints() -> None:
    """Rejects namespaces containing characters unsupported by object IDs."""
    with pytest.raises(SystemExit):
        parse_application_args(["--namespace", "conference2"])
