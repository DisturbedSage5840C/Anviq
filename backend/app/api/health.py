from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.deps import get_redis

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(redis: Annotated[Redis, Depends(get_redis)]) -> JSONResponse:
    """Readiness: dependencies answer. Names what is down, never why (no hosts or errors)."""
    failing: list[str] = []
    try:
        await redis.ping()
    except RedisError:
        failing.append("redis")
    if failing:
        return JSONResponse({"status": "unavailable", "failing": failing}, status_code=503)
    return JSONResponse({"status": "ready"})
