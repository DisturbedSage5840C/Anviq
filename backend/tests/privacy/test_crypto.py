import base64
import os

import pytest

from app.privacy.crypto import (
    DecryptionError,
    FieldCipher,
    InvalidKeyError,
    decode_key,
    phone_hash,
)

KEY = bytes(range(32))
OTHER_KEY = bytes(reversed(range(32)))


def test_encrypt_then_decrypt_round_trips_unicode() -> None:
    cipher = FieldCipher(KEY)

    sealed = cipher.encrypt("919800000001")

    assert cipher.decrypt(sealed) == "919800000001"
    assert cipher.decrypt(cipher.encrypt("नमस्ते")) == "नमस्ते"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    assert b"919800000001" not in FieldCipher(KEY).encrypt("919800000001")


def test_same_plaintext_encrypts_differently_each_time() -> None:
    cipher = FieldCipher(KEY)

    assert cipher.encrypt("x") != cipher.encrypt("x")


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = FieldCipher(KEY)
    sealed = bytearray(cipher.encrypt("secret"))
    sealed[-1] ^= 0x01

    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(sealed))


def test_wrong_key_is_rejected() -> None:
    sealed = FieldCipher(KEY).encrypt("secret")

    with pytest.raises(DecryptionError):
        FieldCipher(OTHER_KEY).decrypt(sealed)


def test_context_binds_ciphertext_to_its_owner() -> None:
    cipher = FieldCipher(KEY)
    sealed = cipher.encrypt("919800000001", context=b"teacher-1")

    assert cipher.decrypt(sealed, context=b"teacher-1") == "919800000001"
    with pytest.raises(DecryptionError):
        cipher.decrypt(sealed, context=b"teacher-2")


def test_truncated_ciphertext_is_rejected() -> None:
    with pytest.raises(DecryptionError):
        FieldCipher(KEY).decrypt(b"short")


def test_cipher_requires_a_256_bit_key() -> None:
    with pytest.raises(InvalidKeyError):
        FieldCipher(b"too-short")


def test_decode_key_accepts_base64_of_32_bytes() -> None:
    assert decode_key(base64.b64encode(KEY).decode()) == KEY


@pytest.mark.parametrize("bad", ["", "not base64!!", base64.b64encode(b"short").decode()])
def test_decode_key_rejects_malformed_or_short_keys(bad: str) -> None:
    with pytest.raises(InvalidKeyError):
        decode_key(bad)


def test_phone_hash_is_deterministic_and_32_bytes() -> None:
    pepper = os.urandom(32)

    assert phone_hash(pepper, "919800000001") == phone_hash(pepper, "919800000001")
    assert len(phone_hash(pepper, "919800000001")) == 32


def test_phone_hash_ignores_formatting_differences() -> None:
    pepper = os.urandom(32)

    assert phone_hash(pepper, "+91 98000 00001") == phone_hash(pepper, "919800000001")


def test_phone_hash_depends_on_the_pepper() -> None:
    assert phone_hash(KEY, "919800000001") != phone_hash(OTHER_KEY, "919800000001")


def test_phone_hash_differs_between_numbers() -> None:
    assert phone_hash(KEY, "919800000001") != phone_hash(KEY, "919800000002")


def test_phone_hash_keeps_letters_so_non_phone_ids_do_not_collapse_to_their_digits() -> None:
    assert phone_hash(KEY, "web:ab12") != phone_hash(KEY, "web:cd12")
    assert phone_hash(KEY, "web:ab12") != phone_hash(KEY, "919800000001")
    assert phone_hash(KEY, "web:ab12") != phone_hash(KEY, "12")
