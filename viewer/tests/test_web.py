from __future__ import annotations

import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

from slack_emoji_fs_viewer.history import HistoryViewer
from slack_emoji_fs_viewer.web import ViewerRequestHandler

from .conftest import HistoryFixture


def request(viewer: HistoryViewer, target: str) -> tuple[int, str, bytes]:
    """Exercise request routing without opening a socket."""
    handler = ViewerRequestHandler.__new__(ViewerRequestHandler)
    handler.server = SimpleNamespace(viewer=viewer)  # type: ignore[assignment]
    handler.path = target
    response: dict[str, Any] = {}

    def capture(status: HTTPStatus, body: bytes, content_type: str) -> None:
        response.update(status=int(status), body=body, content_type=content_type)

    handler._send = capture  # type: ignore[method-assign]
    handler.do_GET()
    return response["status"], response["content_type"], response["body"]


def test_index_and_json_routes(history_fixture: HistoryFixture) -> None:
    viewer = HistoryViewer(history_fixture.repository)
    status, content_type, body = request(viewer, "/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert b"tree &amp; history viewer" in body
    assert b"filesystem-tree" in body
    assert b"function renderTree" in body
    assert b"function renderHistory" in body
    assert b"function renderNode(node, changes, expandAll" in body
    assert b"File size" in body
    assert b"function showRemovedInspector" in body
    assert b"scrollIntoView" in body
    assert b"Snapshot timeline" in body
    assert b"function showPlaybackFrame" in body

    status, _, body = request(viewer, "/api/roots")
    roots = json.loads(body)
    assert status == 200
    assert [root["root_object_id"] for root in roots] == [
        history_fixture.latest_root_id,
        history_fixture.first_root_id,
    ]

    status, _, body = request(viewer, f"/api/tree?root={history_fixture.latest_root_id}")
    tree = json.loads(body)
    assert status == 200
    assert tree["path"] == "/"
    assert [child["name"] for child in tree["children"]] == ["docs", "zeta.txt"]

    status, _, body = request(viewer, f"/api/history?root={history_fixture.latest_root_id}")
    history = json.loads(body)
    assert status == 200
    assert [root["root_object_id"] for root in history] == [
        history_fixture.latest_root_id,
        history_fixture.first_root_id,
    ]

    status, _, body = request(viewer, f"/api/diff?root={history_fixture.latest_root_id}")
    diff = json.loads(body)
    assert status == 200
    assert diff["added_paths"] == ["/docs", "/docs/note.txt", "/zeta.txt"]
    assert diff["tree"]["path"] == "/"


def test_http_validation_and_not_found(history_fixture: HistoryFixture) -> None:
    viewer = HistoryViewer(history_fixture.repository)
    status, content_type, body = request(viewer, "/api/tree")
    assert status == 400
    assert content_type.startswith("application/json")
    assert json.loads(body) == {"error": "Missing required 'root' query parameter"}

    status, _, body = request(viewer, "/not-a-route")
    assert status == 404
    assert json.loads(body) == {"error": "Not found"}
