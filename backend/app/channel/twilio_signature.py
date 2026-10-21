"""Verification of Twilio's X-Twilio-Signature header (HMAC-SHA1 over the URL and form fields)."""

import base64
import hashlib
import hmac
from collections.abc import Sequence


def twilio_signature(auth_token: str, url: str, params: Sequence[tuple[str, str]]) -> str:
    """The base64 HMAC-SHA1 Twilio sends for a POST to `url` with form fields `params`.

    The signed string is the full URL followed by every field as name+value, sorted by
    name, with a repeated name's values sorted too, so the wire order never matters.
    """
    signed = url + "".join(name + value for name, value in sorted(params))
    digest = hmac.new(auth_token.encode(), signed.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def is_valid_twilio_signature(
    auth_token: str, url: str, params: Sequence[tuple[str, str]], header: str | None
) -> bool:
    """True only if `header` is the signature Twilio would compute for this request."""
    if not header:
        return False
    expected = twilio_signature(auth_token, url, params)
    # bytes, because compare_digest on str raises for non-ASCII, and a forged header must be a 401
    return hmac.compare_digest(expected.encode(), header.encode())
