"""GET /dashboard/trends: aggregate trends for the mentor dashboard, behind a bearer token.

The numbers come from `public_trends`, which drops every cell with fewer than 20 teachers in
SQL, so even a leaked token reveals nothing about an individual. The token keeps the endpoint
from being a public scrape target; it is not what protects teachers.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel

from app.api.deps import get_trends_reader
from app.config import Settings, get_settings
from app.dashboard.trends import K_ANONYMITY_THRESHOLD, TrendRow, TrendsReader

router = APIRouter(prefix="/dashboard")

NO_STORE = {"Cache-Control": "no-store"}
BEARER = "bearer"
HTTP_UNAUTHORIZED = 401
HTTP_UNAVAILABLE = 503


class TrendsResponse(BaseModel):
    k_threshold: int
    rows: list[TrendRow]


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status, detail, headers=NO_STORE)


def _presented_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == BEARER else ""


@router.get(
    "/trends",
    response_model=TrendsResponse,
    responses={
        401: {"description": "Missing or wrong bearer token"},
        503: {"description": "The dashboard feed is not configured on this deployment"},
    },
)
async def trends(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[TrendsReader | None, Depends(get_trends_reader)],
    authorization: Annotated[str | None, Header()] = None,
    move_id: Annotated[int | None, Query(ge=1, le=6)] = None,
) -> TrendsResponse:
    response.headers.update(NO_STORE)
    if settings.dashboard_api_token is None or reader is None:
        raise _error(HTTP_UNAVAILABLE, "The dashboard feed is not configured.")
    expected = settings.dashboard_api_token.get_secret_value()
    if not hmac.compare_digest(_presented_token(authorization).encode(), expected.encode()):
        raise _error(HTTP_UNAUTHORIZED, "Missing or wrong dashboard token.")
    return TrendsResponse(
        k_threshold=K_ANONYMITY_THRESHOLD, rows=await reader.trends(move_id=move_id)
    )
