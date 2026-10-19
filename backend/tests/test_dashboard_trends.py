"""GET /dashboard/trends: the only door from the dashboard to teacher data, aggregates only."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_trends_reader
from app.config import Settings, get_settings
from app.dashboard.trends import K_ANONYMITY_THRESHOLD, TrendRow
from app.main import create_app

TOKEN = "dashboard-token-0123456789"
ROW = TrendRow(
    cluster_code="K20",
    move_id=1,
    iso_week="2026-W43",
    n_teachers=24,
    avg_improvement=1.25,
    avg_sessions=4.5,
)


class _Reader:
    def __init__(self) -> None:
        self.rows = [ROW]
        self.calls: list[int | None] = []

    async def trends(self, *, move_id: int | None) -> list[TrendRow]:
        self.calls.append(move_id)
        return self.rows


@pytest.fixture
def reader() -> _Reader:
    return _Reader()


def _client_for(reader: _Reader, token: str | None) -> Iterator[TestClient]:
    settings = Settings(
        wa_verify_token="v", wa_app_secret="s", dashboard_api_token=token, _env_file=None
    )
    app = create_app(settings=settings, manage_resources=False)
    app.dependency_overrides[get_trends_reader] = lambda: reader
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client(reader: _Reader) -> Iterator[TestClient]:
    yield from _client_for(reader, TOKEN)


@pytest.fixture
def unconfigured_client(reader: _Reader) -> Iterator[TestClient]:
    yield from _client_for(reader, None)


def _get(client: TestClient, *, token: str | None = TOKEN, params: dict | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.get("/dashboard/trends", headers=headers, params=params)


def test_returns_the_visible_cells_and_the_threshold_the_page_must_quote(client):
    response = _get(client)

    assert response.status_code == 200
    assert response.json() == {
        "k_threshold": K_ANONYMITY_THRESHOLD,
        "rows": [
            {
                "cluster_code": "K20",
                "move_id": 1,
                "iso_week": "2026-W43",
                "n_teachers": 24,
                "avg_improvement": 1.25,
                "avg_sessions": 4.5,
            }
        ],
    }
    assert response.headers["cache-control"] == "no-store"


def test_an_empty_result_is_a_valid_answer_not_an_error(client, reader):
    reader.rows = []

    response = _get(client)

    assert response.status_code == 200
    assert response.json()["rows"] == []


def test_the_move_filter_reaches_the_reader(client, reader):
    _get(client, params={"move_id": 3})

    assert reader.calls == [3]


@pytest.mark.parametrize("move_id", ["0", "7", "x"])
def test_a_move_outside_one_to_six_is_rejected(client, reader, move_id):
    response = _get(client, params={"move_id": move_id})

    assert response.status_code == 422
    assert reader.calls == []


@pytest.mark.parametrize("token", [None, "wrong-token-0123456789", ""])
def test_a_missing_or_wrong_token_is_refused_without_touching_the_reader(client, reader, token):
    response = _get(client, token=token)

    assert response.status_code == 401
    assert reader.calls == []
    assert response.headers["cache-control"] == "no-store"


def test_the_endpoint_is_off_until_a_token_is_configured(unconfigured_client, reader):
    response = _get(unconfigured_client)

    assert response.status_code == 503
    assert reader.calls == []


def test_a_non_bearer_scheme_is_refused(client):
    response = client.get("/dashboard/trends", headers={"Authorization": f"Basic {TOKEN}"})

    assert response.status_code == 401
