"""The step every channel webhook shares: dedupe, rate-limit and queue one inbound message."""

import logging

from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import JobQueue
from app.channel.messages import InboundMessage
from app.channel.sender_key import sender_key
from app.config import Settings

logger = logging.getLogger(__name__)


class QueueUnavailableError(Exception):
    """The message was valid but could not be queued; its dedupe claim has been released."""


async def admit(
    message: InboundMessage, settings: Settings, guard: InboundGuard, queue: JobQueue
) -> int:
    """Queue one message unless it is a redelivery or its sender is over the limit.

    Returns 1 if queued. Dropped messages are still acked (200) so the provider stops retrying.
    A queue failure releases the dedupe claim and raises QueueUnavailableError, so a redelivery
    or a resend gets through; each webhook decides how to tell its provider.
    """
    if not await guard.claim_message(message.wa_message_id):
        return 0
    if not await guard.allow_sender(sender_key(settings, message.sender_wa_id)):
        logger.warning("sender rate limited; message dropped")
        return 0
    try:
        await queue.enqueue(message.to_envelope(), job_id=message.wa_message_id)
    except Exception as exc:
        await guard.release_message(message.wa_message_id)
        logger.exception("failed to enqueue inbound message")
        raise QueueUnavailableError("queue unavailable") from exc
    return 1
