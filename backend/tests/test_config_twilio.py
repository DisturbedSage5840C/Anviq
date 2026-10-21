import pytest
from pydantic import ValidationError

from app.config import Settings

SID = "AC" + "0" * 32
TOKEN = "twilio-auth-token-value"
FROM = "+14155238886"
WEBHOOK = "https://demo.example.test/webhook/twilio"

TWILIO = {
    "whatsapp_provider": "twilio",
    "twilio_account_sid": SID,
    "twilio_auth_token": TOKEN,
    "twilio_whatsapp_from": FROM,
    "twilio_webhook_url": WEBHOOK,
}


def _settings(**overrides: str) -> Settings:
    return Settings(
        app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None, **overrides
    )


def test_the_provider_defaults_to_meta_and_needs_no_twilio_settings() -> None:
    settings = _settings()

    assert settings.whatsapp_provider == "meta"
    assert settings.twilio_account_sid is None and settings.twilio_auth_token is None


def test_twilio_with_all_four_settings_loads() -> None:
    settings = _settings(**TWILIO)

    assert settings.whatsapp_provider == "twilio"
    assert settings.twilio_account_sid == SID
    assert settings.twilio_whatsapp_from == FROM
    assert settings.twilio_webhook_url == WEBHOOK
    assert settings.twilio_auth_token is not None
    assert settings.twilio_auth_token.get_secret_value() == TOKEN


def test_the_twilio_auth_token_is_not_leaked_in_repr() -> None:
    assert TOKEN not in repr(_settings(**TWILIO))


@pytest.mark.parametrize(
    ("missing", "env_name"),
    [
        ("twilio_account_sid", "TWILIO_ACCOUNT_SID"),
        ("twilio_auth_token", "TWILIO_AUTH_TOKEN"),
        ("twilio_whatsapp_from", "TWILIO_WHATSAPP_FROM"),
        ("twilio_webhook_url", "TWILIO_WEBHOOK_URL"),
    ],
)
def test_the_twilio_provider_names_the_setting_it_is_missing(missing: str, env_name: str) -> None:
    incomplete = {k: v for k, v in TWILIO.items() if k != missing}

    with pytest.raises(ValidationError, match=env_name):
        _settings(**incomplete)


def test_blank_twilio_values_count_as_unset_because_compose_passes_empty_strings() -> None:
    blanks = {k: "" for k in TWILIO if k.startswith("twilio_")}

    assert _settings(**blanks).twilio_account_sid is None
    with pytest.raises(ValidationError, match="TWILIO_ACCOUNT_SID"):
        _settings(whatsapp_provider="twilio", **blanks)


@pytest.mark.parametrize(
    "overrides",
    [
        {"twilio_account_sid": "not-a-sid"},
        {"twilio_account_sid": "AC123"},
        {"twilio_whatsapp_from": "14155238886"},
        {"twilio_whatsapp_from": "whatsapp:+14155238886"},
        {"twilio_webhook_url": "http://demo.example.test/webhook/twilio"},
        {"twilio_webhook_url": "demo.example.test/webhook/twilio"},
        {"whatsapp_provider": "telegram"},
    ],
)
def test_malformed_twilio_settings_are_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _settings(**{**TWILIO, **overrides})


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_provider_means_meta_so_compose_passing_it_empty_does_not_crash(raw: str) -> None:
    assert _settings(whatsapp_provider=raw).whatsapp_provider == "meta"


@pytest.mark.parametrize("raw", ["Twilio", " twilio ", "TWILIO"])
def test_the_provider_name_ignores_case_and_surrounding_spaces(raw: str) -> None:
    settings = _settings(**{**TWILIO, "whatsapp_provider": raw})

    assert settings.whatsapp_provider == "twilio"


def test_an_unknown_provider_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        _settings(whatsapp_provider="telegram")
