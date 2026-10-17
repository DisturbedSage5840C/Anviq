"""FastAPI dependencies for resources created once in the app lifespan."""

from fastapi import Request
from redis.asyncio import Redis

from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue


def get_inbound_guard(request: Request) -> InboundGuard:
    guard: InboundGuard = request.app.state.inbound_guard
    return guard


def get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis
