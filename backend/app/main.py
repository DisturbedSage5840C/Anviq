from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, whatsapp_webhook
from app.config import Settings, get_settings
from app.resources import open_resources


def create_app(*, settings: Settings | None = None, manage_resources: bool = True) -> FastAPI:
    """Build the app. Tests that inject fakes pass manage_resources=False to skip Redis."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_resources(settings or get_settings()) as resources:
            app.state.resources = resources
            app.state.inbound_guard = resources.inbound_guard
            app.state.job_queue = resources.job_queue
            yield

    app = FastAPI(
        title="Anviq",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan if manage_resources else None,
    )
    app.include_router(health.router)
    app.include_router(whatsapp_webhook.router)
    return app


app = create_app()
