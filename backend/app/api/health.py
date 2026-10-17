from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_engine, get_redis

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    redis: Annotated[Redis, Depends(get_redis)],
    engine: Annotated[AsyncEngine, Depends(get_engine)],
) -> JSONResponse:
    """Readiness: dependencies answer. Names what is down, never why (no hosts or errors)."""
    failing: list[str] = []
    try:
        await redis.ping()
    except RedisError:
        failing.append("redis")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except (SQLAlchemyError, OSError):
        failing.append("database")
    if failing:
        return JSONResponse({"status": "unavailable", "failing": failing}, status_code=503)
    return JSONResponse({"status": "ready"})
