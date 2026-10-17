"""Authenticated JSON POSTs to a speech vendor, retrying transient failures.

Never logs request bodies or credentials, and error messages carry only the vendor name and
HTTP status, so audio and keys cannot leak through exceptions.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from app.speech.base import SpeechProviderError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_S = 0.5
REQUEST_TIMEOUT_S = 30.0


class VendorHttp:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        vendor: str,
        auth_headers: Mapping[str, str],
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ) -> None:
        self._http = http
        self._vendor = vendor
        self._auth_headers = dict(auth_headers)
        self._retry_delay_s = retry_delay_s

    async def post(self, url: str, **request: Any) -> dict[str, Any]:
        def send() -> Awaitable[httpx.Response]:
            return self._http.post(
                url, headers=self._auth_headers, timeout=REQUEST_TIMEOUT_S, **request
            )

        for attempt_no in range(1, MAX_ATTEMPTS + 1):
            response = await _attempt(send)
            if response is not None and response.status_code < 400:
                return self._decode(response)
            status = "network error" if response is None else str(response.status_code)
            retryable = response is None or response.status_code in RETRYABLE_STATUS
            if not retryable or attempt_no == MAX_ATTEMPTS:
                raise SpeechProviderError(f"{self._vendor} request failed: {status}")
            logger.warning(
                "speech_retry vendor=%s attempt=%d status=%s", self._vendor, attempt_no, status
            )
            await asyncio.sleep(self._retry_delay_s * attempt_no)
        raise AssertionError("unreachable")  # pragma: no cover

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            raise SpeechProviderError(f"{self._vendor} returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise SpeechProviderError(f"{self._vendor} returned an unexpected response")
        return body


async def _attempt(send: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response | None:
    try:
        return await send()
    except httpx.TransportError:
        return None
