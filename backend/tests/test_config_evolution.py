import pytest
from pydantic import ValidationError

from app.config import Settings

BASE_URL = "http://evolution:8080"
API_KEY = "evolution-global-api-key-value"
INSTANCE = "anviq-demo"
WEBHOOK_SECRET = "evolution-webhook-secret-0123456789"

EVOLUTION = {
    "whatsapp_provider": "evolution",
    "evolution_base_url": BASE_URL,
    "evolution_api_key": API_KEY,
    "evolution_instance": INSTANCE,
    "evolution_webhook_secret": WEBHOOK_SECRET,
}


def _settings(**overrides: str) -> Settings:
    return Settings(
        app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None, **overrides
    )


def test_evolution_with_all_four_settings_loads() -> None:
    settings = _settings(**EVOLUTION)

    assert settings.whatsapp_provider == "evolution"
    assert settings.evolution_base_url == BASE_URL
    assert settings.evolution_instance == INSTANCE
    assert settings.evolution_api_key is not None
    assert settings.evolution_api_key.get_secret_value() == API_KEY
    assert settings.evolution_webhook_secret is not None
    assert settings.evolution_webhook_secret.get_secret_value() == WEBHOOK_SECRET


def test_the_evolution_secrets_are_not_leaked_in_repr() -> None:
    shown = repr(_settings(**EVOLUTION))

    assert API_KEY not in shown
    assert WEBHOOK_SECRET not in shown


@pytest.mark.parametrize(
    ("missing", "env_name"),
    [
        ("evolution_base_url", "EVOLUTION_BASE_URL"),
        ("evolution_api_key", "EVOLUTION_API_KEY"),
        ("evolution_instance", "EVOLUTION_INSTANCE"),
        ("evolution_webhook_secret", "EVOLUTION_WEBHOOK_SECRET"),
    ],
)
def test_the_evolution_provider_names_the_setting_it_is_missing(
    missing: str, env_name: str
) -> None:
    incomplete = {k: v for k, v in EVOLUTION.items() if k != missing}

    with pytest.raises(ValidationError, match=env_name):
        _settings(**incomplete)


def test_blank_evolution_values_count_as_unset_because_compose_passes_empty_strings() -> None:
    blanks = {k: "" for k in EVOLUTION if k.startswith("evolution_")}

    assert _settings(**blanks).evolution_api_key is None
    with pytest.raises(ValidationError, match="EVOLUTION_BASE_URL"):
        _settings(whatsapp_provider="evolution", **blanks)


@pytest.mark.parametrize(
    "overrides",
    [
        {"evolution_base_url": "evolution:8080"},
        {"evolution_base_url": "ftp://evolution:8080"},
        {"evolution_instance": "has space"},
        {"evolution_instance": "../escape"},
        {"evolution_instance": "a" * 65},
        {"evolution_webhook_secret": "too-short"},
    ],
)
def test_malformed_evolution_settings_are_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _settings(**{**EVOLUTION, **overrides})


def test_the_provider_name_ignores_case_for_evolution() -> None:
    settings = _settings(**{**EVOLUTION, "whatsapp_provider": " Evolution "})

    assert settings.whatsapp_provider == "evolution"


def test_the_other_providers_need_no_evolution_settings() -> None:
    assert _settings().evolution_api_key is None
