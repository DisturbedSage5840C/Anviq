"""Async client for Twilio's WhatsApp API, the pilot channel while Meta's business check is pending.

Text in, text out: the sandbox cannot send voice notes or templates. The auth token goes out as
HTTP Basic credentials, and only to the Twilio API host, never into errors or logs.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.channel.whatsapp_client import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAY_S,
    DEFAULT_TIMEOUT_S,
    MAX_MEDIA_BYTES,
    RETRYABLE_STATUS,
    DownloadedMedia,
    MediaTooLargeError,
    WhatsAppError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.twilio.com"
# The Body parameter of one message; a longer reply is sent as several messages.
MAX_BODY_CHARS = 1600
# The sandbox accepts one message every 3 seconds.
DEFAULT_CHUNK_DELAY_S = 3.0
MAX_MEDIA_REDIRECTS = 3
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
# Where Twilio may send a media download: its own hosts and the storage behind them.
MEDIA_REDIRECT_SUFFIXES = (".twilio.com", ".twiliocdn.com", ".amazonaws.com")
UNSUPPORTED = "{} is not supported on the Twilio sandbox"

T = TypeVar("T")


class _RetryableError(Exception):
    def __init__(self, error: WhatsAppError) -> None:
        super().__init__(str(error))
        self.error = error


def split_for_whatsapp(text: str, limit: int = MAX_BODY_CHARS) -> list[str]:
    """`text` cut into pieces of at most `limit` characters, at a line break, then a space."""
    chunks: list[str] = []
    rest = text.strip()
    while len(rest) > limit:
        cut = _break_point(rest, limit)
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return [*chunks, rest] if rest else chunks


def _break_point(text: str, limit: int) -> int:
    for separator in ("\n", " "):
        cut = text.rfind(separator, 0, limit + 1)
        if cut > 0:
            return cut
    return limit


def _describe_failure(response: httpx.Response) -> WhatsAppError:
    code: object = None
    try:
        code = response.json().get("code")
    except (ValueError, AttributeError):
        pass
    return WhatsAppError(f"Twilio API returned {response.status_code} (error code {code})")


class TwilioWhatsAppClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        base_url: str = DEFAULT_BASE_URL,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
        chunk_delay_s: float = DEFAULT_CHUNK_DELAY_S,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_host = httpx.URL(self._base_url).host
        # The only place the auth token is ever sent: this account's own resources.
        self._media_path_prefix = f"/2010-04-01/Accounts/{account_sid}/"
        self._messages_url = f"{self._base_url}{self._media_path_prefix}Messages.json"
        self._auth = httpx.BasicAuth(account_sid, auth_token)
        self._from = f"whatsapp:{from_number}"
        self._max_attempts = max_attempts
        self._retry_delay_s = retry_delay_s
        self._chunk_delay_s = chunk_delay_s

    async def send_text(self, to: str, body: str) -> str:
        """Send `body` as one or more messages and return the first message's sid."""
        chunks = split_for_whatsapp(body)
        if not chunks:
            raise WhatsAppError("Refusing to send an empty reply")
        first_sid = await self._send_one(to, chunks[0])
        for number, chunk in enumerate(chunks[1:], start=2):
            await asyncio.sleep(self._chunk_delay_s)
            try:
                await self._send_one(to, chunk)
            except WhatsAppError:
                # Raising would make the job retry and send the first part to the teacher twice.
                # Later parts after a gap would arrive out of order, so stop here.
                logger.warning("twilio reply chunk %d of %d failed", number, len(chunks))
                break
        return first_sid

    async def send_audio(self, to: str, media_id: str) -> str:
        raise WhatsAppError(UNSUPPORTED.format("Voice replies are"))

    async def upload_media(self, data: bytes, mime_type: str) -> str:
        raise WhatsAppError(UNSUPPORTED.format("Media upload is"))

    async def send_template(self, to: str, name: str, language_code: str) -> str:
        raise WhatsAppError(UNSUPPORTED.format("Template messages are"))

    async def download_media(self, media_id: str) -> DownloadedMedia:
        """Fetch a media URL from an inbound webhook; `media_id` is that full URL."""
        first_url = self._checked_first_url(media_id)
        return await self._retrying(lambda: self._fetch_media(first_url))

    async def _send_one(self, to: str, body: str) -> str:
        form = {"From": self._from, "To": f"whatsapp:+{to}", "Body": body}

        async def attempt() -> httpx.Response:
            return await self._http.post(
                self._messages_url, auth=self._auth, data=form, timeout=DEFAULT_TIMEOUT_S
            )

        payload = await self._retrying(lambda: self._json(attempt))
        sid = payload.get("sid") if isinstance(payload, dict) else None
        if not isinstance(sid, str) or not sid:
            raise WhatsAppError("Twilio accepted the send but returned no message sid")
        return sid

    def _checked_first_url(self, url: str) -> httpx.URL:
        """The media URL must be an https URL on the Twilio API host, with no credentials in it."""
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL:
            raise WhatsAppError("Refusing a media URL that is not valid") from None
        on_api_host = parsed.host == self._api_host and parsed.port is None
        in_own_account = parsed.path.startswith(self._media_path_prefix)
        if parsed.scheme != "https" or not on_api_host or not in_own_account or parsed.userinfo:
            raise WhatsAppError("Refusing a media URL that is not on the Twilio API host")
        return parsed

    def _checked_redirect(self, current: httpx.URL, location: str) -> httpx.URL:
        target = current.join(location)
        if target.scheme != "https" or target.port is not None or target.userinfo:
            raise WhatsAppError("Refusing a media redirect that is not plain https")
        if target.host != self._api_host and not target.host.endswith(MEDIA_REDIRECT_SUFFIXES):
            raise WhatsAppError("Refusing a media redirect to a host Twilio does not use")
        return target

    async def _fetch_media(self, first_url: httpx.URL) -> DownloadedMedia:
        url = first_url
        for _ in range(MAX_MEDIA_REDIRECTS + 1):
            outcome = await self._get_once(url)
            if isinstance(outcome, DownloadedMedia):
                return outcome
            url = self._checked_redirect(url, outcome)
        raise WhatsAppError("Too many media redirects")

    async def _get_once(self, url: httpx.URL) -> DownloadedMedia | str:
        """One hop: the media, or the Location to follow. Credentials go to the API host only."""
        auth = self._auth if url.host == self._api_host else None
        async with self._http.stream(
            "GET", url, auth=auth, follow_redirects=False, timeout=DEFAULT_TIMEOUT_S
        ) as response:
            if response.status_code in REDIRECT_STATUS:
                return _location(response)
            if response.status_code in RETRYABLE_STATUS:
                raise _RetryableError(_media_failure(response))
            if not response.is_success:
                raise _media_failure(response)
            return await _read_capped(response)

    async def _json(self, attempt: Callable[[], Awaitable[httpx.Response]]) -> Any:
        response = await attempt()
        if response.status_code in RETRYABLE_STATUS:
            raise _RetryableError(_describe_failure(response))
        if response.is_error:
            raise _describe_failure(response)
        try:
            return response.json()
        except ValueError:
            return None

    async def _retrying(self, run: Callable[[], Awaitable[T]]) -> T:
        last: WhatsAppError | None = None
        for attempt_no in range(1, self._max_attempts + 1):
            try:
                return await run()
            except _RetryableError as exc:
                last = exc.error
            except httpx.TransportError as exc:
                last = WhatsAppError(f"Twilio transport failure: {type(exc).__name__}")
            logger.warning("twilio_retry attempt=%d", attempt_no)
            if attempt_no < self._max_attempts:
                await asyncio.sleep(self._retry_delay_s * attempt_no)
        if last is None:
            raise WhatsAppError("Twilio client configured with zero attempts")
        raise last


def _location(response: httpx.Response) -> str:
    location = response.headers.get("location", "")
    if not location:
        raise WhatsAppError("Twilio media redirect carried no location")
    return str(location)


def _media_failure(response: httpx.Response) -> WhatsAppError:
    return WhatsAppError(f"Twilio media download returned {response.status_code}")


async def _read_capped(response: httpx.Response) -> DownloadedMedia:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_MEDIA_BYTES:
        raise MediaTooLargeError("Media is over the 16 MB cap")
    chunks: list[bytes] = []
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > MAX_MEDIA_BYTES:
            raise MediaTooLargeError("Media body is over the 16 MB cap")
        chunks.append(chunk)
    mime_type = response.headers.get("content-type", "")
    return DownloadedMedia(data=b"".join(chunks), mime_type=mime_type)
