import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SCHEMA_AND_DOC_PATHS = ["/openapi.json", "/docs", "/redoc"]


@pytest.mark.parametrize("path", SCHEMA_AND_DOC_PATHS)
def test_api_schema_and_docs_pages_are_not_served(path: str):
    app = create_app(manage_resources=False)

    response = TestClient(app).get(path)

    assert response.status_code == 404
