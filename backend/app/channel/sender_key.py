"""Opaque per-sender key for rate limiting; raw phone numbers never reach Redis."""

from app.config import Settings
from app.privacy.crypto import decode_key, phone_hash

# Only reachable when APP_ENV=local: Settings rejects a missing pepper in staging/prod.
_LOCAL_DEV_PEPPER = b"anviq-local-dev-pepper-not-secret"


def sender_key(settings: Settings, wa_id: str) -> str:
    pepper = (
        decode_key(settings.phone_pepper.get_secret_value())
        if settings.phone_pepper is not None
        else _LOCAL_DEV_PEPPER
    )
    return phone_hash(pepper, wa_id).hex()
