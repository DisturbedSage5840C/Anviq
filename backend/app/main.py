from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from app.api import dashboard, health, web_room, whatsapp_webhook
from app.config import Settings, WebRoomSettings, get_settings
from app.dashboard.trends import PostgresTrendsReader
from app.ops.sentry import init_sentry
from app.resources import open_resources
from app.web.demo_codes import PostgresDemoCodes
from app.web.turn import build_web_turn

WEB_PREFLIGHT_MAX_AGE_S = 600


@asynccontextmanager
async def _dashboard_reader(settings: Settings) -> AsyncIterator[PostgresTrendsReader | None]:
    """A dashboard_ro engine of its own, so the feed can never reach a private table."""
    if settings.dashboard_database_url is None:
        yield None
        return
    engine = create_async_engine(settings.dashboard_database_url.get_secret_value())
    try:
        yield PostgresTrendsReader(engine)
    finally:
        await engine.dispose()


def create_app(
    *,
    settings: Settings | None = None,
    manage_resources: bool = True,
    web_allowed_origins: list[str] | None = None,
) -> FastAPI:
    """Build the app. Tests that inject fakes pass manage_resources=False to skip Redis."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = settings or get_settings()
        init_sentry(active.sentry_dsn, environment=active.app_env)
        async with open_resources(active) as resources:
            app.state.resources = resources
            app.state.redis = resources.redis
            app.state.engine = resources.engine
            app.state.inbound_guard = resources.inbound_guard
            app.state.job_queue = resources.job_queue
            app.state.demo_codes = PostgresDemoCodes(
                resources.engine, resources.keyring.phone_pepper
            )
            app.state.web_turn = build_web_turn(resources, active)
            async with _dashboard_reader(active) as reader:
                app.state.trends_reader = reader
                yield

    app = FastAPI(
        title="Anviq",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan if manage_resources else None,
    )
    app.include_router(health.router)
    app.include_router(whatsapp_webhook.router)
    app.include_router(web_room.router)
    app.include_router(dashboard.router)
    origins = (
        web_allowed_origins
        if web_allowed_origins is not None
        else WebRoomSettings().web_allowed_origins
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["POST"],
            allow_headers=["Content-Type", "X-Demo-Code"],
            max_age=WEB_PREFLIGHT_MAX_AGE_S,
        )
    return app


app = create_app()
