from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.ai import build_ask, build_daily_loop, build_llm
from app.config import Settings
from app.core.ask.answer import AskAnviq
from app.core.daily_loop import PipelineDailyLoop


def _settings(**extra: object) -> Settings:
    return Settings(wa_verify_token="v", wa_app_secret="s", _env_file=None, **extra)  # type: ignore[arg-type]


def _resources() -> SimpleNamespace:
    return SimpleNamespace(http=httpx.AsyncClient(), engine=object())


def test_without_a_key_nothing_model_backed_is_built():
    resources = _resources()
    assert build_llm(resources, _settings()) is None  # type: ignore[arg-type]
    assert build_daily_loop(resources, _settings()) is None  # type: ignore[arg-type]
    assert build_ask(resources, _settings()) is None  # type: ignore[arg-type]


def test_with_a_key_the_daily_loop_and_ask_are_built():
    resources = _resources()
    settings = _settings(anthropic_api_key=SecretStr("sk-test"))
    assert isinstance(build_daily_loop(resources, settings), PipelineDailyLoop)  # type: ignore[arg-type]
    assert isinstance(build_ask(resources, settings), AskAnviq)  # type: ignore[arg-type]
