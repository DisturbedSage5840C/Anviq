import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def sign(body: bytes, secret: str = TEST_APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
