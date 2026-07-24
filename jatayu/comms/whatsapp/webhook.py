"""WhatsApp webhook routes for FastAPI.

Provides two endpoints mounted at /api/comms/whatsapp/webhook:
  GET  — Meta verification handshake (called once during webhook setup)
  POST — Receive incoming messages from WhatsApp users

Security:
  - GET verifies the hub.verify_token matches our configured token.
  - POST verifies the X-Hub-Signature-256 header using HMAC-SHA256
    with the APP_SECRET to ensure the request came from Meta.

The POST handler returns 200 immediately, then processes the message
asynchronously in a background task to avoid Meta retries.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from jatayu.comms.whatsapp.parser import parse_whatsapp_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/comms/whatsapp", tags=["whatsapp"])

# Module-level reference to the CommunicationRouter — set by server.py
_comm_router = None


def set_comm_router(comm_router) -> None:
    """Called by server.py on startup to inject the CommunicationRouter."""
    global _comm_router
    _comm_router = comm_router
    logger.info("WhatsApp webhook router connected to CommunicationRouter")


# ── Webhook verification (GET) ──

@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification handshake.

    Meta sends a GET request with:
      hub.mode      = "subscribe"
      hub.verify_token = your configured token
      hub.challenge = a string to echo back

    We verify the token and return the challenge to confirm ownership.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "jatayu_whatsapp_verify_2026")

    if mode == "subscribe" and token == verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("WhatsApp webhook verification FAILED (bad token)")
    return PlainTextResponse(content="Forbidden", status_code=403)


# ── Webhook receiver (POST) ──

@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages from Meta.

    Pipeline:
      1. Verify X-Hub-Signature-256 signature
      2. Return 200 immediately (required by Meta)
      3. Parse payload and dispatch to CommunicationRouter in background
    """
    body = await request.body()

    # ── Signature verification ──
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()
    if app_secret:
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(body, signature_header, app_secret):
            logger.warning("WhatsApp webhook signature verification FAILED")
            return PlainTextResponse(content="Forbidden", status_code=403)

    # ── Parse JSON payload ──
    try:
        payload = await request.json()
    except Exception:
        return PlainTextResponse(content="OK", status_code=200)

    # ── Quick check: is this a message or just a status update? ──
    has_messages = False
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("value", {}).get("messages"):
                has_messages = True
                break

    if has_messages and _comm_router:
        # Process in background so we return 200 immediately
        background_tasks.add_task(_process_payload, payload)

    # Meta requires 200 response within 5 seconds
    return PlainTextResponse(content="OK", status_code=200)


# ── Background processing ──

async def _process_payload(payload: dict) -> None:
    """Parse the webhook payload and dispatch each message to the router."""
    try:
        messages = parse_whatsapp_payload(payload)
        for message in messages:
            logger.info(
                "WhatsApp message from %s (%s): type=%s text=%.60s",
                message.sender_name,
                message.sender_id,
                message.metadata.get("whatsapp_type", "unknown"),
                message.text or "[media]",
            )
            await _comm_router.handle_incoming(message)
    except Exception as e:
        logger.error("WhatsApp webhook processing failed: %s", e, exc_info=True)


# ── Signature verification ──

def _verify_signature(body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify the X-Hub-Signature-256 header using HMAC-SHA256.

    Args:
        body:             Raw request body bytes.
        signature_header: Value of X-Hub-Signature-256 header (e.g. "sha256=abc123...").
        app_secret:       Meta App Secret for HMAC computation.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header[7:]  # Strip "sha256=" prefix
    computed_sig = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_sig, expected_sig)
