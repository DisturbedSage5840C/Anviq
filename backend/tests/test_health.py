from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.api.deps import get_engine, get_redis


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


class _Connection:
    async def __aenter__(self) -> "_Connection":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        return None


class _HealthyEngine:
    def connect(self) -> _Connection:
        return _Connection()


class _DownEngine:
    def connect(self) -> _Connection:
        raise OperationalError("select 1", {}, Exception("secret-db-host:5432 refused"))


def _wire(client, *, redis, engine) -> None:
    client.app.dependency_overrides[get_redis] = redis
    client.app.dependency_overrides[get_engine] = engine


def test_readyz_is_ready_when_redis_and_the_database_answer(client):
    _wire(client, redis=_HealthyRedis, engine=_HealthyEngine)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_which_dependency_is_down_without_leaking_details(client):
    _wire(client, redis=_DownRedis, engine=_HealthyEngine)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failing": ["redis"]}
    assert "secret-host" not in response.text


def test_readyz_names_the_database_when_only_it_is_down(client):
    _wire(client, redis=_HealthyRedis, engine=_DownEngine)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failing": ["database"]}
    assert "secret-db-host" not in response.text


def test_readyz_lists_every_failing_dependency(client):
    _wire(client, redis=_DownRedis, engine=_DownEngine)

    response = client.get("/readyz")

    assert response.json()["failing"] == ["redis", "database"]
