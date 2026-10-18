"""Thin async client for the Meta WhatsApp Cloud API.

Only what Anviq needs: text, voice notes, reply buttons, media upload/download.
The access token is sent as a Bearer header and never appears in errors or logs.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 16 * 1024 * 1024
OGG_OPUS_MIME = "audio/ogg; codecs=opus"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_S = 0.5
DEFAULT_TIMEOUT_S = 15.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_BUTTONS = 3

T = TypeVar("T")


class WhatsAppError(Exception):
    """Graph API call failed. The message carries the status and Meta error code only."""


class MediaTooLargeError(WhatsAppError):
    """Media exceeds the 16 MB cap."""


class _RetryableError(Exception):
    def __init__(self, error: WhatsAppError) -> None:
        super().__init__(str(error))
        self.error = error


@dataclass(frozen=True)
class DownloadedMedia:
    data: bytes
    mime_type: str


def _describe_failure(response: httpx.Response) -> WhatsAppError:
    code: object = None
    try:
        code = response.json().get("error", {}).get("code")
    except (ValueError, AttributeError):
        pass
    return WhatsAppError(f"WhatsApp API returned {response.status_code} (error code {code})")


class WhatsAppClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        phone_number_id: str,
        access_token: str,
        base_url: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._http = http
        self._phone_number_id = phone_number_id
        self._base_url = base_url.rstrip("/")
        self._auth = {"Authorization": f"Bearer {access_token}"}
        self._max_attempts = max_attempts
        self._retry_delay_s = retry_delay_s

    async def send_text(self, to: str, body: str) -> str:
        return await self._send_message(to, "text", {"text": {"body": body, "preview_url": False}})

    async def send_template(self, to: str, name: str, language_code: str) -> str:
        """Send an approved template: the only message Meta allows outside the 24h window."""
        template = {"name": name, "language": {"code": language_code}}
        return await self._send_message(to, "template", {"template": template})

    async def send_audio(self, to: str, media_id: str) -> str:
        return await self._send_message(to, "audio", {"audio": {"id": media_id, "voice": True}})

    async def send_buttons(self, to: str, body: str, buttons: Sequence[tuple[str, str]]) -> str:
        if not 1 <= len(buttons) <= MAX_BUTTONS:
            raise ValueError(f"WhatsApp reply buttons accept 1 to {MAX_BUTTONS} options")
        interactive = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": button_id, "title": title}}
                    for button_id, title in buttons
                ]
            },
        }
        return await self._send_message(to, "interactive", {"interactive": interactive})

    async def upload_media(self, data: bytes, mime_type: str) -> str:
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaTooLargeError("Refusing to upload media over the 16 MB cap")

        async def attempt() -> httpx.Response:
            return await self._http.post(
                f"{self._base_url}/{self._phone_number_id}/media",
                headers=self._auth,
                data={"messaging_product": "whatsapp"},
                files={"file": ("voice", data, mime_type)},
                timeout=DEFAULT_TIMEOUT_S,
            )

        payload = await self._json(attempt)
        return str(payload["id"])

    async def download_media(self, media_id: str) -> DownloadedMedia:
        """Two steps: resolve the short-lived URL, then fetch it with the same Bearer token."""

        async def resolve() -> httpx.Response:
            return await self._http.get(
                f"{self._base_url}/{media_id}", headers=self._auth, timeout=DEFAULT_TIMEOUT_S
            )

        meta = await self._json(resolve)
        if _to_int(meta.get("file_size")) > MAX_MEDIA_BYTES:
            raise MediaTooLargeError("Media is over the 16 MB cap")
        data = await self._retrying(lambda: self._fetch_capped(str(meta["url"])))
        return DownloadedMedia(data=data, mime_type=str(meta.get("mime_type", "")))

    async def _send_message(self, to: str, kind: str, content: dict[str, Any]) -> str:
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": kind,
            **content,
        }

        async def attempt() -> httpx.Response:
            return await self._http.post(
                f"{self._base_url}/{self._phone_number_id}/messages",
                headers=self._auth,
                json=body,
                timeout=DEFAULT_TIMEOUT_S,
            )

        payload = await self._json(attempt)
        try:
            return str(payload["messages"][0]["id"])
        except (KeyError, IndexError, TypeError):
            raise WhatsAppError("WhatsApp accepted the send but returned no message id") from None

    async def _fetch_capped(self, url: str) -> bytes:
        chunks: list[bytes] = []
        received = 0
        async with self._http.stream(
            "GET", url, headers=self._auth, timeout=DEFAULT_TIMEOUT_S
        ) as response:
            if response.status_code in RETRYABLE_STATUS:
                raise _RetryableError(_describe_failure(response))
            if response.is_error:
                raise _describe_failure(response)
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > MAX_MEDIA_BYTES:
                    raise MediaTooLargeError("Media body is over the 16 MB cap")
                chunks.append(chunk)
        return b"".join(chunks)

    async def _json(self, attempt: Callable[[], Awaitable[httpx.Response]]) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            response = await attempt()
            if response.status_code in RETRYABLE_STATUS:
                raise _RetryableError(_describe_failure(response))
            if response.is_error:
                raise _describe_failure(response)
            result: dict[str, Any] = response.json()
            return result

        return await self._retrying(run)

    async def _retrying(self, run: Callable[[], Awaitable[T]]) -> T:
        last: WhatsAppError | None = None
        for attempt_no in range(1, self._max_attempts + 1):
            try:
                return await run()
            except _RetryableError as exc:
                last = exc.error
            except httpx.TransportError as exc:
                last = WhatsAppError(f"WhatsApp transport failure: {type(exc).__name__}")
            logger.warning("whatsapp_retry attempt=%d", attempt_no)
            if attempt_no < self._max_attempts:
                await asyncio.sleep(self._retry_delay_s * attempt_no)
        if last is None:
            raise WhatsAppError("WhatsApp client configured with zero attempts")
        raise last


def _to_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
