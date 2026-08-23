import logging
import time
from collections.abc import Callable
from io import BytesIO
from typing import override
from urllib.request import urlopen

from PIL import Image
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.http_retry.builtin_handlers import (
    ConnectionErrorRetryHandler,
    RateLimitErrorRetryHandler,
    ServerErrorRetryHandler,
)

from slack_emoji_fs.object_store import png_encoding
from slack_emoji_fs.object_store.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreUnavailableError,
)
from slack_emoji_fs.object_store.object_store import ObjectStore

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (1.0, 2.0, 4.0)
_TRANSIENT_SLACK_ERRORS = {
    "error_bad_format",
    "failed_to_add_emoji",
    "fatal_error",
    "file_update_failed",
    "internal_error",
    "ratelimited",
    "request_timeout",
    "service_unavailable",
    "temporarily_unavailable",
}


def _download_image(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


class SlackEmojiObjectStore(ObjectStore):
    def __init__(
            self,
            slack_token: str,
            *,
            cache_ttl: float = 60,
            client: WebClient | None = None,
            downloader: Callable[[str], bytes] = _download_image,
            clock: Callable[[], float] = time.monotonic,
            sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or WebClient(token=slack_token)
        self._cache_ttl = cache_ttl
        self._downloader = downloader
        self._clock = clock
        self._sleeper = sleeper
        self._emoji_urls: dict[str, str] = {}
        self._emoji_cache_loaded_at: float | None = None
        self._payload_cache: dict[str, bytes] = {}

        retry_handler_types = (
            ConnectionErrorRetryHandler,
            RateLimitErrorRetryHandler,
            ServerErrorRetryHandler,
        )
        self._client.retry_handlers = [
            handler
            for handler in self._client.retry_handlers
            if not isinstance(handler, retry_handler_types)
        ]
        self._client.retry_handlers.extend([
            ConnectionErrorRetryHandler(max_retry_count=3),
            RateLimitErrorRetryHandler(max_retry_count=3),
            ServerErrorRetryHandler(max_retry_count=3),
        ])

        self._call_with_retries(
            "auth.test",
            "Slack workspace",
            self._client.auth_test,
        )

    def _call_with_retries[T](
            self,
            operation: str,
            subject: str,
            call: Callable[[], T],
    ) -> T:
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                logger.info("Slack API: %s for %s", operation, subject)
                return call()
            except SlackApiError as error:
                error_code = error.response.get("error")
                if (
                        error_code not in _TRANSIENT_SLACK_ERRORS
                        or attempt == len(_RETRY_DELAYS)
                ):
                    raise
                failure = str(error_code)
            except SlackClientError as error:
                if attempt == len(_RETRY_DELAYS):
                    raise
                failure = str(error)

            delay = _RETRY_DELAYS[attempt]
            logger.warning(
                "Slack API: %s failed for %s (%s); retrying in %.0fs",
                operation,
                subject,
                failure,
                delay,
            )
            self._sleeper(delay)

        raise AssertionError("unreachable")

    def _download_with_retries(self, object_id: str, image_url: str) -> bytes:
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                logger.info("Slack CDN: download emoji %s", object_id)
                return self._downloader(image_url)
            except OSError as error:
                if attempt == len(_RETRY_DELAYS):
                    raise
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "Slack CDN: download failed for %s (%s); retrying in %.0fs",
                    object_id,
                    error,
                    delay,
                )
                self._sleeper(delay)

        raise AssertionError("unreachable")

    def _refresh_emoji_cache(self) -> None:
        if (
                self._emoji_cache_loaded_at is not None
                and self._clock() - self._emoji_cache_loaded_at < self._cache_ttl
        ):
            return

        try:
            response = self._call_with_retries(
                "emoji.list",
                "Slack workspace",
                lambda: self._client.emoji_list(include_categories=False),
            )
        except SlackClientError as error:
            raise ObjectStoreUnavailableError("Could not list Slack emoji") from error

        emoji_data = response.get("emoji")
        if not isinstance(emoji_data, dict):
            raise ObjectStoreUnavailableError("Slack returned no emoji mapping")

        self._emoji_urls = {
            name: url
            for name, url in emoji_data.items()
            if isinstance(name, str) and isinstance(url, str)
        }
        self._emoji_cache_loaded_at = self._clock()

    @override
    def list_ids(self) -> list[str]:
        self._refresh_emoji_cache()
        return sorted(
            emoji_id
            for emoji_id, emoji_url in self._emoji_urls.items()
            if emoji_id.startswith("efs_") and not emoji_url.startswith("alias:")
        )

    @override
    def put(self, object_id: str, object_data: bytes) -> None:
        if object_id in self.list_ids():
            raise ObjectAlreadyExistsError(f"Object already exists with id {object_id}")

        image = png_encoding.encode_png_data(object_data)
        png_buffer = BytesIO()
        image.save(png_buffer, format="PNG")
        uploaded_file_id: str | None = None
        operation = "files.uploadV2"

        try:
            upload_response = self._call_with_retries(
                operation,
                object_id,
                lambda: self._client.files_upload_v2(
                        filename=f"{object_id}.png",
                        file=png_buffer.getvalue(),
                        title=object_id,
                ),
            )
            uploaded_file = upload_response.get("file")
            if not isinstance(uploaded_file, dict):
                raise ObjectStoreUnavailableError("Slack returned no uploaded file")

            uploaded_file_id = uploaded_file.get("id")
            if not isinstance(uploaded_file_id, str):
                raise ObjectStoreUnavailableError("Slack returned no uploaded file ID")

            operation = "files.sharedPublicURL"
            public_response = self._call_with_retries(
                operation,
                uploaded_file_id,
                lambda: self._client.files_sharedPublicURL(
                    file=uploaded_file_id
                ),
            )
            public_file = public_response.get("file")
            if not isinstance(public_file, dict):
                raise ObjectStoreUnavailableError("Slack returned no public file")

            private_url = public_file.get("url_private")
            public_url = public_file.get("permalink_public")
            if not isinstance(private_url, str) or not isinstance(public_url, str):
                raise ObjectStoreUnavailableError("Slack returned no public file URL")

            public_secret = public_url.rsplit("-", maxsplit=1)[-1]
            separator = "&" if "?" in private_url else "?"
            image_url = f"{private_url}{separator}pub_secret={public_secret}"
            operation = "admin.emoji.add"
            self._call_with_retries(
                operation,
                object_id,
                lambda: self._client.admin_emoji_add(
                    url=image_url,
                    name=object_id,
                ),
            )
        except SlackApiError as error:
            error_code = error.response.get("error")
            logger.error(
                "Slack API: %s failed for %s: %s",
                operation,
                object_id,
                error_code,
            )
            if error_code in {"error_name_taken", "error_name_taken_i18n"}:
                raise ObjectAlreadyExistsError(
                    f"Object already exists with id {object_id}"
                ) from error
            raise ObjectStoreUnavailableError("Could not add Slack emoji") from error
        except SlackClientError as error:
            logger.error(
                "Slack API: %s failed for %s: %s",
                operation,
                object_id,
                error,
            )
            raise ObjectStoreUnavailableError("Could not stage Slack emoji") from error
        finally:
            if uploaded_file_id is not None:
                try:
                    self._call_with_retries(
                        "files.delete",
                        uploaded_file_id,
                        lambda: self._client.files_delete(file=uploaded_file_id),
                    )
                except SlackClientError as error:
                    logger.warning(
                        "Could not delete Slack staging file %s: %s",
                        uploaded_file_id,
                        error,
                    )

        self._payload_cache[object_id] = object_data
        self._emoji_urls[object_id] = ""
        self._emoji_cache_loaded_at = self._clock()

    @override
    def get(self, object_id: str) -> bytes | None:
        if object_id in self._payload_cache:
            return self._payload_cache[object_id]

        self._refresh_emoji_cache()
        image_url = self._emoji_urls.get(object_id)
        if image_url is None or image_url.startswith("alias:"):
            return None

        try:
            image_data = self._download_with_retries(object_id, image_url)
            with Image.open(BytesIO(image_data)) as image:
                object_data = png_encoding.decode_png_data(image.convert("RGBA"))
        except (OSError, ValueError) as error:
            raise ObjectStoreUnavailableError(
                f"Could not retrieve Slack emoji object {object_id}"
            ) from error

        self._payload_cache[object_id] = object_data
        return object_data
