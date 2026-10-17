"""Integration test: needs a reachable Redis at REDIS_URL (CI service or docker compose)."""

import uuid

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.resources import open_resources


def _settings(**overrides: object) -> Settings:
    return Settings(
        app_env="local",
        wa_verify_token="t",
        wa_app_secret="s",
        _env_file=None,
        **overrides,  # type: ignore[arg-type]
    )


async def test_queue_and_guard_share_one_working_redis() -> None:
    message_id = f"wamid.test-{uuid.uuid4().hex}"

    async with open_resources(_settings()) as resources:
        assert await resources.inbound_guard.claim_message(message_id) is True
        assert await resources.inbound_guard.claim_message(message_id) is False
        await resources.job_queue.enqueue({"wa_message_id": message_id}, job_id=message_id)
        await resources.job_queue.enqueue({"wa_message_id": message_id}, job_id=message_id)

        queued = [job.job_id for job in await resources.arq_pool.queued_jobs()]
        assert queued.count(message_id) == 1  # arq ignores a repeated job id

        await resources.inbound_guard.release_message(message_id)
        await resources.arq_pool.delete(f"arq:job:{message_id}")
        await resources.arq_pool.zrem("arq:queue", message_id)


async def test_whatsapp_client_is_absent_without_credentials() -> None:
    async with open_resources(_settings()) as resources:
        assert resources.whatsapp is None


async def test_whatsapp_client_is_built_when_credentials_are_set() -> None:
    settings = _settings(wa_phone_number_id="123", wa_access_token="tok")

    async with open_resources(settings) as resources:
        assert resources.whatsapp is not None


async def test_http_client_is_closed_on_exit() -> None:
    async with open_resources(_settings()) as resources:
        http: httpx.AsyncClient = resources.http

    assert http.is_closed


async def test_unreachable_redis_fails_fast_with_clear_error() -> None:
    settings = _settings(redis_url="redis://127.0.0.1:1/0")

    with pytest.raises(RedisConnectionError):
        async with open_resources(settings, conn_retries=0):
            pass


async def test_app_lifespan_wires_webhook_to_the_real_queue() -> None:
    import json

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app
    from tests.conftest import sign

    settings = _settings()
    message_id = f"wamid.test-{uuid.uuid4().hex}"
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": message_id,
                                        "from": "919999999999",
                                        "type": "text",
                                        "text": {"body": "Namaste"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        response = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": sign(body, "s")},
        )

    # Inspect from this test's own event loop; the app's pool lived in the client's loop.
    async with open_resources(settings) as resources:
        queued = [job.job_id for job in await resources.arq_pool.queued_jobs()]
        await resources.inbound_guard.release_message(message_id)
        await resources.arq_pool.delete(f"arq:job:{message_id}")
        await resources.arq_pool.zrem("arq:queue", message_id)

    assert response.status_code == 200
    assert message_id in queued
