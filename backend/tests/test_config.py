import base64

import pytest
from pydantic import ValidationError

from app.config import Settings, WebRoomSettings


def test_missing_whatsapp_secrets_fail_at_startup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WA_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("WA_APP_SECRET", raising=False)
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


def test_graph_api_base_url_follows_configured_version():
    settings = Settings(
        app_env="local",
        wa_verify_token="v",
        wa_app_secret="s",
        wa_graph_version="v24.0",
        _env_file=None,
    )
    assert settings.wa_graph_base_url == "https://graph.facebook.com/v24.0"


def test_graph_version_defaults_to_a_current_release():
    settings = Settings(app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None)
    assert settings.wa_graph_version == "v25.0"


def test_graph_version_rejects_malformed_values():
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            wa_verify_token="v",
            wa_app_secret="s",
            wa_graph_version="25",
            _env_file=None,
        )


VALID_KEY = base64.b64encode(bytes(range(32))).decode()


def _deployed(**overrides):
    base = {
        "app_env": "prod",
        "wa_verify_token": "v",
        "wa_app_secret": "s",
        "anthropic_api_key": "k",
        "sarvam_api_key": "k",
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})


def test_deployed_env_requires_field_key_and_phone_pepper():
    with pytest.raises(ValidationError, match="FIELD_KEY"):
        _deployed()
    with pytest.raises(ValidationError, match="PHONE_PEPPER"):
        _deployed(field_key=VALID_KEY)


def test_deployed_env_accepts_all_required_secrets():
    settings = _deployed(field_key=VALID_KEY, phone_pepper=VALID_KEY)
    assert settings.app_env == "prod"


def test_malformed_field_key_is_rejected_at_startup():
    with pytest.raises(ValidationError, match="FIELD_KEY"):
        _deployed(field_key="a" * 44, phone_pepper=VALID_KEY)


def test_deployed_env_requires_the_selected_speech_provider_key():
    with pytest.raises(ValidationError, match="SARVAM_API_KEY"):
        _deployed(field_key=VALID_KEY, phone_pepper=VALID_KEY, sarvam_api_key=None)


def test_deployed_env_needs_google_key_only_when_google_is_selected():
    with pytest.raises(ValidationError, match="GOOGLE_SPEECH_API_KEY"):
        _deployed(field_key=VALID_KEY, phone_pepper=VALID_KEY, stt_provider="google")
    settings = _deployed(
        field_key=VALID_KEY,
        phone_pepper=VALID_KEY,
        stt_provider="google",
        google_speech_api_key="g",
    )
    assert settings.stt_provider == "google"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["https://a.example"]', ["https://a.example"]),
        ("https://a.example", ["https://a.example"]),
        ("https://a.example, https://b.example/", ["https://a.example", "https://b.example"]),
        ("", []),
        (" , ", []),
    ],
)
def test_web_origins_accept_json_or_comma_separated_and_never_crash(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
):
    monkeypatch.setenv("WEB_ALLOWED_ORIGINS", raw)

    assert WebRoomSettings(_env_file=None).web_allowed_origins == expected


def test_web_origins_default_to_none_allowed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WEB_ALLOWED_ORIGINS", raising=False)

    assert WebRoomSettings(_env_file=None).web_allowed_origins == []


def test_sentry_is_off_without_a_dsn_and_the_dsn_is_never_printed():
    off = Settings(app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None)
    on = Settings(
        app_env="local",
        wa_verify_token="v",
        wa_app_secret="s",
        sentry_dsn="https://key@o0.ingest.sentry.io/1",
        _env_file=None,
    )

    assert off.sentry_dsn is None
    assert "ingest.sentry.io" not in repr(on)
