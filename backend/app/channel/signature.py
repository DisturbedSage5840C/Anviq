"""Verification of Meta's X-Hub-Signature-256 header."""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def is_valid_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    """True only if `header` is the HMAC-SHA256 of the raw body under `app_secret`."""
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    received = header.removeprefix(SIGNATURE_PREFIX)
    return hmac.compare_digest(expected, received)
