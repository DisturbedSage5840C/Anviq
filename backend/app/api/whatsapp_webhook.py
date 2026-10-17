"""WhatsApp Cloud API webhook: handshake (GET) and signed event delivery (POST)."""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.channel.signature import is_valid_signature
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/whatsapp")

SUBSCRIBE_MODE = "subscribe"


@router.get("")
async def verify_webhook(
    settings: Annotated[Settings, Depends(get_settings)],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    if mode != SUBSCRIBE_MODE or token != settings.wa_verify_token.get_secret_value():
        raise HTTPException(status_code=403, detail="verification failed")
    return Response(content=challenge or "", media_type="text/plain")


@router.post("")
async def receive_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, str]:
    body = await request.body()
    if not is_valid_signature(body, signature, settings.wa_app_secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    # Message handling (dedupe + enqueue) arrives in task M2b. Never log message content.
    logger.info("whatsapp webhook accepted", extra={"bytes": len(body)})
    return {"status": "received"}
