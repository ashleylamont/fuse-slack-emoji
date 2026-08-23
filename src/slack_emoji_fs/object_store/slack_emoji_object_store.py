import logging
import time
from collections.abc import Callable
from io import BytesIO
from typing import override
from urllib.request import urlopen

from PIL import Image
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from slack_emoji_fs.object_store import png_encoding
from slack_emoji_fs.object_store.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreUnavailableError,
)
from slack_emoji_fs.object_store.object_store import ObjectStore

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._client = client or WebClient(token=slack_token)
        self._client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
        logger.info("Slack API: auth.test")
        self._client.auth_test()

        self._cache_ttl = cache_ttl
        self._downloader = downloader
        self._clock = clock
        self._emoji_urls: dict[str, str] = {}
        self._emoji_cache_loaded_at: float | None = None
        self._payload_cache: dict[str, bytes] = {}

    def _refresh_emoji_cache(self) -> None:
        if (
                self._emoji_cache_loaded_at is not None
                and self._clock() - self._emoji_cache_loaded_at < self._cache_ttl
        ):
            return

        try:
            logger.info("Slack API: emoji.list")
            response = self._client.emoji_list(include_categories=False)
        except SlackApiError as error:
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
            logger.info("Slack API: files.uploadV2 for %s", object_id)
            upload_response = self._client.files_upload_v2(
                filename=f"{object_id}.png",
                file=png_buffer.getvalue(),
                title=object_id,
            )
            uploaded_file = upload_response.get("file")
            if not isinstance(uploaded_file, dict):
                raise ObjectStoreUnavailableError("Slack returned no uploaded file")

            uploaded_file_id = uploaded_file.get("id")
            if not isinstance(uploaded_file_id, str):
                raise ObjectStoreUnavailableError("Slack returned no uploaded file ID")

            operation = "files.sharedPublicURL"
            logger.info(
                "Slack API: files.sharedPublicURL for staging file %s",
                uploaded_file_id,
            )
            public_response = self._client.files_sharedPublicURL(
                file=uploaded_file_id
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
            logger.info("Slack API: admin.emoji.add for %s", object_id)
            self._client.admin_emoji_add(url=image_url, name=object_id)
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
                    logger.info(
                        "Slack API: files.delete for staging file %s",
                        uploaded_file_id,
                    )
                    self._client.files_delete(file=uploaded_file_id)
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
            logger.info("Slack CDN: download emoji %s", object_id)
            image_data = self._downloader(image_url)
            with Image.open(BytesIO(image_data)) as image:
                object_data = png_encoding.decode_png_data(image.convert("RGBA"))
        except (OSError, ValueError) as error:
            raise ObjectStoreUnavailableError(
                f"Could not retrieve Slack emoji object {object_id}"
            ) from error

        self._payload_cache[object_id] = object_data
        return object_data
