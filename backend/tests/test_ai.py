from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

import app.ai
from app.ai import build_llm, build_router_brain
from app.channel.model_budget import RedisModelBudget
from app.config import Settings
from app.core.ask.answer import AskAnviq
from app.core.daily_loop import PipelineDailyLoop
from app.core.rehearsal_flow import RehearsalFlow
from app.core.router_brain import RouterBrain
from app.llm.client import LLMClient


def _settings(**extra: object) -> Settings:
    return Settings(wa_verify_token="v", wa_app_secret="s", _env_file=None, **extra)  # type: ignore[arg-type]


def _resources() -> SimpleNamespace:
    return SimpleNamespace(
        http=httpx.AsyncClient(),
        engine=object(),
        redis=object(),
        teacher_store=object(),
        keyring=SimpleNamespace(phone_pepper=bytes(32)),
    )


def test_without_a_key_there_is_no_model_client():
    assert build_llm(_resources(), _settings()) is None  # type: ignore[arg-type]


def test_with_a_key_the_brain_has_the_daily_loop_ask_and_the_practice():
    brain = build_router_brain(
        _resources(),  # type: ignore[arg-type]
        _settings(anthropic_api_key=SecretStr("sk-test")),
    )

    assert isinstance(brain, RouterBrain)
    assert isinstance(brain._loop, PipelineDailyLoop)  # type: ignore[attr-defined]
    assert isinstance(brain._loop._asker, AskAnviq)  # type: ignore[attr-defined]
    assert isinstance(brain._rehearsal, RehearsalFlow)  # type: ignore[attr-defined]
    budget = brain._budget  # type: ignore[attr-defined]
    assert isinstance(budget, RedisModelBudget)


def test_the_loop_ask_and_the_practice_share_one_model_client(monkeypatch: pytest.MonkeyPatch):
    built: list[LLMClient] = []

    def counting(*args: object, **kwargs: object) -> LLMClient:
        built.append(LLMClient(*args, **kwargs))  # type: ignore[arg-type]
        return built[-1]

    monkeypatch.setattr(app.ai, "LLMClient", counting)

    build_router_brain(
        _resources(),  # type: ignore[arg-type]
        _settings(anthropic_api_key=SecretStr("sk-test")),
    )

    assert len(built) == 1


def test_without_a_key_the_brain_has_no_model_steps_but_still_a_budget():
    brain = build_router_brain(_resources(), _settings(max_model_steps_per_day=7))  # type: ignore[arg-type]

    assert brain._loop is None  # type: ignore[attr-defined]
    assert brain._rehearsal is None  # type: ignore[attr-defined]
    budget = brain._budget  # type: ignore[attr-defined]
    assert isinstance(budget, RedisModelBudget)
    assert budget._limit == 7
