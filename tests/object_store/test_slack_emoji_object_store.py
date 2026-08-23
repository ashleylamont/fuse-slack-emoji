from io import BytesIO
from typing import Any

import pytest
from PIL import Image
from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.web.slack_response import SlackResponse

from slack_emoji_fs.object_store import png_encoding
from slack_emoji_fs.object_store.errors import ObjectAlreadyExistsError
from slack_emoji_fs.object_store.slack_emoji_object_store import SlackEmojiObjectStore


def _response(client: WebClient, data: dict[str, object]) -> SlackResponse:
    return SlackResponse(
        client=client,
        http_verb="POST",
        api_url="https://slack.test/api",
        req_args={},
        data=data,
        headers={},
        status_code=200,
    )


def _encoded_png(payload: bytes) -> bytes:
    image = png_encoding.encode_png_data(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeSlackClient(WebClient):
    def __init__(self, emoji: dict[str, str] | None = None) -> None:
        self.retry_handlers = []
        self.emoji = dict(emoji or {})
        self.auth_calls = 0
        self.list_calls = 0
        self.add_calls: list[tuple[str, str]] = []
        self.upload_calls: list[tuple[str, bytes, str]] = []
        self.deleted_file_ids: list[str] = []

    def auth_test(self, **kwargs: Any) -> SlackResponse:
        self.auth_calls += 1
        return _response(self, {"ok": True})

    def emoji_list(
            self,
            include_categories: bool | None = None,
            **kwargs: Any,
    ) -> SlackResponse:
        self.list_calls += 1
        return _response(self, {"ok": True, "emoji": dict(self.emoji)})

    def admin_emoji_add(
            self,
            *,
            name: str,
            url: str,
            **kwargs: Any,
    ) -> SlackResponse:
        self.add_calls.append((name, url))
        self.emoji[name] = "https://emoji.slack-edge.com/test/image.png"
        return _response(self, {"ok": True})

    def files_upload_v2(
            self,
            *,
            filename: str | None = None,
            file: str | bytes | Any | None = None,
            title: str | None = None,
            **kwargs: Any,
    ) -> SlackResponse:
        assert filename is not None
        assert isinstance(file, bytes)
        assert title is not None
        self.upload_calls.append((filename, file, title))
        return _response(self, {"ok": True, "file": {"id": "FSTAGED"}})

    def files_sharedPublicURL(
            self,
            *,
            file: str,
            **kwargs: Any,
    ) -> SlackResponse:
        assert file == "FSTAGED"
        return _response(self, {
            "ok": True,
            "file": {
                "id": file,
                "url_private": "https://files.slack.com/files-pri/team-file/object.png",
                "permalink_public": "https://slack-files.com/team-file-publicsecret",
            },
        })

    def files_delete(self, *, file: str, **kwargs: Any) -> SlackResponse:
        self.deleted_file_ids.append(file)
        return _response(self, {"ok": True})


def test_initialization_authenticates_and_installs_a_rate_limit_handler() -> None:
    """The store validates its client and enables a bounded Slack rate-limit retry."""
    client = FakeSlackClient()

    SlackEmojiObjectStore("token", client=client)

    assert client.auth_calls == 1
    retry_handlers = [
        handler
        for handler in client.retry_handlers
        if isinstance(handler, RateLimitErrorRetryHandler)
    ]
    assert len(retry_handlers) == 1
    assert retry_handlers[0].max_retry_count == 3


def test_list_ids_filters_non_objects_and_reuses_fresh_metadata() -> None:
    """Metadata listing returns real EFS objects and avoids repeated Slack calls within its TTL."""
    client = FakeSlackClient({
        "efs_v1_tests_dat_1_data": "https://emoji.slack-edge.com/data.png",
        "efs_v1_tests_dat_2_alias": "alias:another_emoji",
        "ordinary_emoji": "https://emoji.slack-edge.com/ordinary.png",
    })
    now = [100.0]
    store = SlackEmojiObjectStore(
        "token",
        client=client,
        clock=lambda: now[0],
        cache_ttl=30,
    )

    assert store.list_ids() == ["efs_v1_tests_dat_1_data"]
    assert store.list_ids() == ["efs_v1_tests_dat_1_data"]
    assert client.list_calls == 1

    now[0] += 31
    store.list_ids()
    assert client.list_calls == 2


def test_put_stages_a_png_in_slack_files_and_is_immediately_readable() -> None:
    """Writes stage a public Slack file, create the emoji, and remove the staging file."""
    client = FakeSlackClient()
    download_calls: list[str] = []
    store = SlackEmojiObjectStore(
        "token",
        client=client,
        downloader=lambda url: download_calls.append(url) or b"unused",
    )

    store.put("efs_v1_tests_dat_1_object", b"payload")

    filename, encoded_image, title = client.upload_calls[0]
    assert filename == "efs_v1_tests_dat_1_object.png"
    assert title == "efs_v1_tests_dat_1_object"
    with Image.open(BytesIO(encoded_image)) as image:
        assert image.format == "PNG"
    assert client.add_calls == [(
        "efs_v1_tests_dat_1_object",
        "https://files.slack.com/files-pri/team-file/object.png"
        "?pub_secret=publicsecret",
    )]
    assert client.deleted_file_ids == ["FSTAGED"]
    assert store.get("efs_v1_tests_dat_1_object") == b"payload"
    assert download_calls == []
    assert "efs_v1_tests_dat_1_object" in store.list_ids()


def test_get_downloads_decodes_and_caches_remote_payload() -> None:
    """A remote Slack PNG is decoded once and then served from the immutable payload cache."""
    object_id = "efs_v1_tests_dat_1_remote"
    image_url = "https://emoji.slack-edge.com/test/remote.png"
    client = FakeSlackClient({object_id: image_url})
    download_calls: list[str] = []
    store = SlackEmojiObjectStore(
        "token",
        client=client,
        downloader=lambda url: download_calls.append(url) or _encoded_png(b"remote payload"),
    )

    assert store.get(object_id) == b"remote payload"
    assert store.get(object_id) == b"remote payload"
    assert download_calls == [image_url]


def test_put_rejects_an_id_present_in_cached_slack_metadata() -> None:
    """Slack-backed writes retain the append-only ObjectStore duplicate contract."""
    object_id = "efs_v1_tests_dat_1_existing"
    client = FakeSlackClient({object_id: "https://emoji.slack-edge.com/existing.png"})
    store = SlackEmojiObjectStore("token", client=client)

    with pytest.raises(ObjectAlreadyExistsError):
        store.put(object_id, b"replacement")

    assert client.add_calls == []
