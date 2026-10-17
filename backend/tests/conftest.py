import hashlib
import hmac
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_inbound_guard, get_job_queue
from app.config import Settings, get_settings
from app.main import create_app

TEST_VERIFY_TOKEN = "test-verify-token"
TEST_APP_SECRET = "test-app-secret"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="local",
        wa_verify_token=TEST_VERIFY_TOKEN,
        wa_app_secret=TEST_APP_SECRET,
        _env_file=None,
    )


class AllowAllGuard:
    """Stands in for InboundGuard in tests that don't exercise dedupe or rate limiting."""

    async def claim_message(self, wa_message_id: str) -> bool:
        return True

    async def release_message(self, wa_message_id: str) -> None:
        return None

    async def allow_sender(self, sender_key: str) -> bool:
        return True


class DiscardQueue:
    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        return None


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(manage_resources=False)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_inbound_guard] = AllowAllGuard
    app.dependency_overrides[get_job_queue] = DiscardQueue
    return TestClient(app)


def sign(body: bytes, secret: str = TEST_APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
