"""The API turns on error reporting when it starts, with the deployed environment."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main


def test_api_startup_turns_on_error_reporting(monkeypatch: pytest.MonkeyPatch):
    started: list[tuple[object, str]] = []
    resources = SimpleNamespace(
        redis=None,
        engine=None,
        inbound_guard=None,
        job_queue=None,
        keyring=SimpleNamespace(phone_pepper=b"p"),
    )

    @asynccontextmanager
    async def fake_open(_: object):
        yield resources

    settings: Any = SimpleNamespace(sentry_dsn="dsn", app_env="prod")
    monkeypatch.setattr(main, "open_resources", fake_open)
    monkeypatch.setattr(main, "build_web_turn", lambda *_: object())
    monkeypatch.setattr(main, "PostgresDemoCodes", lambda *_: object())
    monkeypatch.setattr(
        main, "init_sentry", lambda dsn, *, environment: started.append((dsn, environment))
    )

    with TestClient(main.create_app(settings=settings, web_allowed_origins=[])):
        pass

    assert started == [("dsn", "prod")]
