from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.deps import get_redis


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _HealthyRedis:
    async def ping(self) -> bool:
        return True


class _DownRedis:
    async def ping(self) -> bool:
        raise RedisConnectionError("secret-host:6379 refused")


def test_readyz_is_ready_when_redis_answers(client):
    client.app.dependency_overrides[get_redis] = _HealthyRedis

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_which_dependency_is_down_without_leaking_details(client):
    client.app.dependency_overrides[get_redis] = _DownRedis

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failing": ["redis"]}
    assert "secret-host" not in response.text
