from fastapi import FastAPI

from app.api import health, whatsapp_webhook


def create_app() -> FastAPI:
    app = FastAPI(title="Anviq", docs_url=None, redoc_url=None)
    app.include_router(health.router)
    app.include_router(whatsapp_webhook.router)
    return app


app = create_app()
