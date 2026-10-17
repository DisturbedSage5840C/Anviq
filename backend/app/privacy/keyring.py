"""Builds the privacy key material from settings."""

import logging
import os
from dataclasses import dataclass

from pydantic import SecretStr

from app.config import DEPLOYED_ENVS, Settings
from app.privacy.crypto import KEY_BYTES, FieldCipher, InvalidKeyError, decode_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Keyring:
    field_cipher: FieldCipher
    phone_pepper: bytes


def load_keyring(settings: Settings) -> Keyring:
    """Decode FIELD_KEY and PHONE_PEPPER; outside deployed envs, missing ones are throwaway.

    A throwaway pepper changes every restart, so hashes from one run never match the next.
    That is fine for a laptop and wrong for anything real, hence the hard failure when deployed.
    """
    field_key = _key_or_throwaway("FIELD_KEY", settings.field_key, settings)
    pepper = _key_or_throwaway("PHONE_PEPPER", settings.phone_pepper, settings)
    return Keyring(field_cipher=FieldCipher(field_key), phone_pepper=pepper)


def _key_or_throwaway(name: str, secret: SecretStr | None, settings: Settings) -> bytes:
    if secret is not None:
        return decode_key(secret.get_secret_value())
    if settings.app_env in DEPLOYED_ENVS:
        raise InvalidKeyError(f"{name} is required when APP_ENV={settings.app_env}")
    logger.warning("%s is unset; using a throwaway key for this process only", name)
    return os.urandom(KEY_BYTES)
