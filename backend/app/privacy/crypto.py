"""Field-level encryption and keyed phone hashing.

AES-256-GCM protects the one reversible field (the WhatsApp id needed to reply).
Lookups use an HMAC of the phone number so the raw number is never an index.
"""

import base64
import binascii
import hashlib
import hmac
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
_NON_DIGITS = re.compile(r"\D")


class InvalidKeyError(ValueError):
    """Key material is missing, malformed or the wrong length."""


class DecryptionError(Exception):
    """Ciphertext failed authentication, so it was tampered with or the key is wrong."""


def decode_key(encoded: str) -> bytes:
    """Decode a base64 secret and require exactly 256 bits."""
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidKeyError("Key is not valid base64") from None
    if len(key) != KEY_BYTES:
        raise InvalidKeyError(f"Key must decode to {KEY_BYTES} bytes")
    return key


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise InvalidKeyError(f"Key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, *, context: bytes = b"") -> bytes:
        """Return nonce || ciphertext || tag. `context` is authenticated but not stored."""
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext.encode(), context or None)

    def decrypt(self, sealed: bytes, *, context: bytes = b"") -> str:
        if len(sealed) < NONCE_BYTES + TAG_BYTES:
            raise DecryptionError("Ciphertext is too short")
        nonce, body = sealed[:NONCE_BYTES], sealed[NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, body, context or None).decode()
        except InvalidTag:
            raise DecryptionError("Ciphertext failed authentication") from None


def phone_hash(pepper: bytes, phone: str) -> bytes:
    """HMAC-SHA256 over the digits of a phone number, so formatting never changes the hash."""
    digits = _NON_DIGITS.sub("", phone)
    return hmac.new(pepper, digits.encode(), hashlib.sha256).digest()
