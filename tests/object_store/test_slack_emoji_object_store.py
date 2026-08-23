from io import BytesIO
from typing import Any

import pytest
from PIL import Image
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import (
    ConnectionErrorRetryHandler,
    RateLimitErrorRetryHandler,
    ServerErrorRetryHandler,
)
from slack_sdk.web.slack_response import SlackResponse

from slack_emoji_fs.object_store import png_encoding
from slack_emoji_fs.object_store.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreUnavailableError,
)
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
        self.list_error_codes: list[str] = []
        self.add_calls: list[tuple[str, str]] = []
        self.add_attempts = 0
        self.add_error_codes: list[str] = []
        self.upload_calls: list[tuple[str, bytes, str]] = []
        self.upload_attempts = 0
        self.upload_error_codes: list[str] = []
        self.public_attempts = 0
        self.public_error_codes: list[str] = []
        self.delete_attempts = 0
        self.delete_error_codes: list[str] = []
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
        if self.list_error_codes:
            error_code = self.list_error_codes.pop(0)
            raise SlackApiError(
                "The emoji list failed",
                _response(self, {"ok": False, "error": error_code}),
            )
        return _response(self, {"ok": True, "emoji": dict(self.emoji)})

    def admin_emoji_add(
            self,
            *,
            name: str,
            url: str,
            **kwargs: Any,
    ) -> SlackResponse:
        self.add_attempts += 1
        if self.add_error_codes:
            error_code = self.add_error_codes.pop(0)
            raise SlackApiError(
                "Adding the emoji failed",
                _response(self, {"ok": False, "error": error_code}),
            )
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
        self.upload_attempts += 1
        if self.upload_error_codes:
            error_code = self.upload_error_codes.pop(0)
            raise SlackApiError(
                "The staging upload failed",
                _response(self, {"ok": False, "error": error_code}),
            )
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
        self.public_attempts += 1
        if self.public_error_codes:
            error_code = self.public_error_codes.pop(0)
            raise SlackApiError(
                "Sharing the staging file failed",
                _response(self, {"ok": False, "error": error_code}),
            )
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
        self.delete_attempts += 1
        if self.delete_error_codes:
            error_code = self.delete_error_codes.pop(0)
            raise SlackApiError(
                "Deleting the staging file failed",
                _response(self, {"ok": False, "error": error_code}),
            )
        self.deleted_file_ids.append(file)
        return _response(self, {"ok": True})


def test_initialization_authenticates_and_installs_transport_retry_handlers() -> None:
    """The store enables bounded connection, rate-limit, and server-error retries."""
    client = FakeSlackClient()

    SlackEmojiObjectStore("token", client=client)

    assert client.auth_calls == 1
    for handler_type in (
        ConnectionErrorRetryHandler,
        RateLimitErrorRetryHandler,
        ServerErrorRetryHandler,
    ):
        retry_handlers = [
            handler
            for handler in client.retry_handlers
            if isinstance(handler, handler_type)
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


def test_list_ids_retries_transient_slack_errors() -> None:
    """Object discovery tolerates temporary Slack application errors."""
    client = FakeSlackClient({
        "efs_v1_tests_dat_1_data": "https://emoji.slack-edge.com/data.png",
    })
    client.list_error_codes = ["internal_error"]
    delays: list[float] = []
    store = SlackEmojiObjectStore("token", client=client, sleeper=delays.append)

    assert store.list_ids() == ["efs_v1_tests_dat_1_data"]
    assert client.list_calls == 2
    assert delays == [1.0]


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


def test_get_retries_transient_cdn_download_failures() -> None:
    """Remote object reads retry temporary CDN/network failures before decoding."""
    object_id = "efs_v1_tests_dat_1_remote"
    client = FakeSlackClient({
        object_id: "https://emoji.slack-edge.com/test/remote.png",
    })
    attempts = 0
    delays: list[float] = []

    def download(_: str) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary CDN failure")
        return _encoded_png(b"remote payload")

    store = SlackEmojiObjectStore(
        "token",
        client=client,
        downloader=download,
        sleeper=delays.append,
    )

    assert store.get(object_id) == b"remote payload"
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_put_rejects_an_id_present_in_cached_slack_metadata() -> None:
    """Slack-backed writes retain the append-only ObjectStore duplicate contract."""
    object_id = "efs_v1_tests_dat_1_existing"
    client = FakeSlackClient({object_id: "https://emoji.slack-edge.com/existing.png"})
    store = SlackEmojiObjectStore("token", client=client)

    with pytest.raises(ObjectAlreadyExistsError):
        store.put(object_id, b"replacement")

    assert client.add_calls == []


def test_put_retries_transient_slack_staging_failures() -> None:
    """A transient Slack Files failure is retried before surfacing an I/O error."""
    client = FakeSlackClient()
    client.upload_error_codes = ["file_update_failed", "file_update_failed"]
    delays: list[float] = []
    store = SlackEmojiObjectStore("token", client=client, sleeper=delays.append)

    store.put("efs_v1_tests_dat_1_retry", b"payload")

    assert client.upload_attempts == 3
    assert delays == [1.0, 2.0]
    assert client.deleted_file_ids == ["FSTAGED"]


def test_put_retries_public_link_emoji_add_and_cleanup_operations() -> None:
    """Every Slack stage used by a write tolerates a temporary application error."""
    client = FakeSlackClient()
    client.public_error_codes = ["internal_error"]
    client.add_error_codes = ["error_bad_format", "failed_to_add_emoji"]
    client.delete_error_codes = ["service_unavailable"]
    delays: list[float] = []
    store = SlackEmojiObjectStore("token", client=client, sleeper=delays.append)

    store.put("efs_v1_tests_dat_1_retry_all", b"payload")

    assert client.public_attempts == 2
    assert client.add_attempts == 3
    assert client.delete_attempts == 2
    assert delays == [1.0, 1.0, 2.0, 1.0]


def test_put_stops_after_bounded_staging_retries() -> None:
    """Persistent Slack Files failures become an unavailable-store error after three retries."""
    client = FakeSlackClient()
    client.upload_error_codes = ["file_update_failed"] * 4
    delays: list[float] = []
    store = SlackEmojiObjectStore("token", client=client, sleeper=delays.append)

    with pytest.raises(ObjectStoreUnavailableError):
        store.put("efs_v1_tests_dat_1_retry", b"payload")

    assert client.upload_attempts == 4
    assert delays == [1.0, 2.0, 4.0]
