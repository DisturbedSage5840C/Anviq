"""FastAPI dependencies for resources created once in the app lifespan."""

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.web.demo_codes import PostgresDemoCodes
from app.web.turn import WebTurn


def get_inbound_guard(request: Request) -> InboundGuard:
    guard: InboundGuard = request.app.state.inbound_guard
    return guard


def get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_demo_codes(request: Request) -> PostgresDemoCodes:
    codes: PostgresDemoCodes = request.app.state.demo_codes
    return codes


def get_web_turn(request: Request) -> WebTurn:
    turn: WebTurn = request.app.state.web_turn
    return turn
