import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_whatsapp_secrets_fail_at_startup():
    with pytest.raises(ValidationError):
        Settings(app_env="local", _env_file=None)


def test_local_env_needs_only_whatsapp_secrets():
    settings = Settings(app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None)
    assert settings.app_env == "local"


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_deployed_env_requires_anthropic_key(env: str):
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(app_env=env, wa_verify_token="v", wa_app_secret="s", _env_file=None)


def test_secrets_are_not_leaked_in_repr():
    settings = Settings(
        app_env="local", wa_verify_token="v", wa_app_secret="topsecret", _env_file=None
    )
    assert "topsecret" not in repr(settings)
