"""Async client for a self-hosted Evolution API, the unofficial WhatsApp Web bridge for the demo.

It runs on a spare SIM and breaks WhatsApp's terms, so it is a demo channel and never the
production one. Every call carries the global API key in an `apikey` header, to the one configured
host only; the key never reaches errors or logs.
"""

import asyncio
import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.channel.whatsapp_client import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAY_S,
    DEFAULT_TIMEOUT_S,
    MAX_MEDIA_BYTES,
    OGG_OPUS_MIME,
    RETRYABLE_STATUS,
    DownloadedMedia,
    MediaTooLargeError,
    WhatsAppError,
)

logger = logging.getLogger(__name__)

# Four base64 characters carry three bytes, so this bounds the audio before it is decoded.
BASE64_BYTES_PER_CHAR = 3 / 4

T = TypeVar("T")

TransportErrors = tuple[type[httpx.TransportError], ...]
# Failing before the request left the machine means nothing was delivered, so a send can repeat.
# A read timeout or reset may come after WhatsApp accepted it, and repeating would reply twice.
_NOTHING_SENT: TransportErrors = (httpx.ConnectError, httpx.ConnectTimeout)
_ANY_TRANSPORT_ERROR: TransportErrors = (httpx.TransportError,)


class _RetryableError(Exception):
    def __init__(self, error: WhatsAppError) -> None:
        super().__init__(str(error))
        self.error = error


def _describe_failure(response: httpx.Response) -> WhatsAppError:
    # The body is left out on purpose: it can echo request fields.
    return WhatsAppError(f"Evolution API returned {response.status_code}")


class EvolutionWhatsAppClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        instance: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._http = http
        root = base_url.rstrip("/")
        self._send_text_url = f"{root}/message/sendText/{instance}"
        self._send_audio_url = f"{root}/message/sendWhatsAppAudio/{instance}"
        self._media_url = f"{root}/chat/getBase64FromMediaMessage/{instance}"
        self._headers = {"apikey": api_key}
        self._max_attempts = max_attempts
        self._retry_delay_s = retry_delay_s

    async def send_text(self, to: str, body: str) -> str:
        if not body.strip():
            raise WhatsAppError("Refusing to send an empty reply")
        return await self._send(self._send_text_url, {"number": to, "text": body})

    async def upload_media(self, data: bytes, mime_type: str) -> str:
        """Evolution has no upload step: the audio travels with the send.

        So the "media id" is the audio itself, base64-encoded, and `send_audio` posts it.
        """
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaTooLargeError("Media is over the 16 MB cap")
        return base64.b64encode(data).decode("ascii")

    async def send_audio(self, to: str, media_id: str) -> str:
        # encoding=False sends our OGG/Opus bytes as they are, as a voice note.
        payload = {"number": to, "audio": media_id, "encoding": False}
        return await self._send(self._send_audio_url, payload)

    async def send_template(self, to: str, name: str, language_code: str) -> str:
        raise WhatsAppError("Template messages are not supported on the Evolution channel")

    async def download_media(self, media_id: str) -> DownloadedMedia:
        """Fetch an inbound voice note; `media_id` is the WhatsApp message id from the webhook."""
        request = {"message": {"key": {"id": media_id}}}
        payload = await self._post(self._media_url, request, retry_on=_ANY_TRANSPORT_ERROR)
        return _decode_media(payload)

    async def _send(self, url: str, payload: dict[str, Any]) -> str:
        response = await self._post(url, payload, retry_on=_NOTHING_SENT)
        key = response.get("key") if isinstance(response, dict) else None
        message_id = key.get("id") if isinstance(key, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise WhatsAppError("Evolution accepted the send but returned no message id")
        return message_id

    async def _post(self, url: str, payload: dict[str, Any], *, retry_on: TransportErrors) -> Any:
        async def attempt() -> Any:
            response = await self._http.post(
                url, json=payload, headers=self._headers, timeout=DEFAULT_TIMEOUT_S
            )
            if response.status_code in RETRYABLE_STATUS:
                raise _RetryableError(_describe_failure(response))
            if response.is_error:
                raise _describe_failure(response)
            try:
                return response.json()
            except ValueError:
                return None

        return await self._retrying(attempt, retry_on)

    async def _retrying(self, run: Callable[[], Awaitable[T]], retry_on: TransportErrors) -> T:
        last: WhatsAppError | None = None
        for attempt_no in range(1, self._max_attempts + 1):
            try:
                return await run()
            except _RetryableError as exc:
                last = exc.error
            except httpx.TransportError as exc:
                failure = WhatsAppError(f"Evolution transport failure: {type(exc).__name__}")
                if not isinstance(exc, retry_on):
                    raise failure from None
                last = failure
            logger.warning("evolution_retry attempt=%d", attempt_no)
            if attempt_no < self._max_attempts:
                await asyncio.sleep(self._retry_delay_s * attempt_no)
        if last is None:
            raise WhatsAppError("Evolution client configured with zero attempts")
        raise last


def _decode_media(payload: Any) -> DownloadedMedia:
    encoded = payload.get("base64") if isinstance(payload, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise WhatsAppError("Evolution returned no media for that message")
    if len(encoded) * BASE64_BYTES_PER_CHAR > MAX_MEDIA_BYTES:
        raise MediaTooLargeError("Media is over the 16 MB cap")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise WhatsAppError("Evolution returned media that is not valid base64") from None
    mime_type = payload.get("mimetype")
    if not isinstance(mime_type, str) or not mime_type:
        mime_type = OGG_OPUS_MIME
    return DownloadedMedia(data=data, mime_type=mime_type)
