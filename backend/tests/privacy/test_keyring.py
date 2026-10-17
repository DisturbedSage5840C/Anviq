import base64
import logging

import pytest

from app.config import Settings
from app.privacy.crypto import InvalidKeyError
from app.privacy.keyring import load_keyring

KEY_A = base64.b64encode(bytes(range(32))).decode()
KEY_B = base64.b64encode(bytes(range(32, 64))).decode()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "local",
        "wa_verify_token": "v",
        "wa_app_secret": "s",
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_configured_keys_are_decoded_and_used():
    keyring = load_keyring(_settings(field_key=KEY_A, phone_pepper=KEY_B))

    assert keyring.phone_pepper == bytes(range(32, 64))
    sealed = keyring.field_cipher.encrypt("919876543210")
    assert keyring.field_cipher.decrypt(sealed) == "919876543210"


def test_local_runs_without_keys_get_throwaway_ones_and_a_warning(
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.WARNING, logger="app.privacy.keyring"):
        first = load_keyring(_settings())
        second = load_keyring(_settings())

    assert len(first.phone_pepper) == 32
    assert first.phone_pepper != second.phone_pepper
    assert "FIELD_KEY" in caplog.text and "PHONE_PEPPER" in caplog.text


def test_a_half_configured_local_keyring_is_filled_in_per_key():
    keyring = load_keyring(_settings(phone_pepper=KEY_B))

    assert keyring.phone_pepper == bytes(range(32, 64))


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_deployed_envs_never_fall_back_to_throwaway_keys(env: str):
    settings = _settings().model_copy(update={"app_env": env})

    with pytest.raises(InvalidKeyError, match="FIELD_KEY"):
        load_keyring(settings)
