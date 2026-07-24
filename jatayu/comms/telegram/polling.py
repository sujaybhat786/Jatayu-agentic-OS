"""Telegram Long Polling Service — standalone, separate from the adapter.

This module is the ONLY Telegram-specific service that knows about polling.
If you later switch to webhooks, you delete this file and create a webhook.py
instead. The adapter, parser, router, and dispatcher remain completely untouched.

Polling flow:
  start_telegram_polling()
      └── loop forever:
              GET /getUpdates?timeout=30&offset=<last+1>
              for each update:
                  parse_telegram_update() → IncomingMessage
                  comm_router.handle_incoming(message)

The polling loop is an asyncio Task started at server startup.
It runs in the background and never blocks the main event loop.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from jatayu.comms.telegram.parser import parse_telegram_update

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"

# Long-poll timeout in seconds — Telegram holds the connection open
# for this duration waiting for updates, then returns an empty list.
_POLL_TIMEOUT = 30

# How long to wait before retrying after a network or API error
_RETRY_DELAY = 5


async def start_telegram_polling(
    token: str,
    comm_router,
    authorized_users: list[str] | None = None,
) -> None:
    """Start the Telegram long polling loop as an asyncio Task.

    This function runs indefinitely. It should be scheduled via
    asyncio.create_task() at server startup and stored so it can
    be cancelled on shutdown.

    Args:
        token:            Telegram Bot API token.
        comm_router:      CommunicationRouter instance to dispatch updates.
        authorized_users: Optional list of Telegram user IDs (as strings)
                          to accept. If empty/None, all users are accepted.
                          The FIRST message from any user will log their ID,
                          making it easy to find your own ID on first use.
    """
    base_url = _API_BASE.format(token=token)
    offset: int | None = None  # Next update_id to fetch from

    logger.info("Telegram long polling started")
    print("📨  Telegram polling active — send a message to your bot!")

    while True:
        try:
            updates = await _fetch_updates(base_url, offset)

            for update in updates:
                update_id = update.get("update_id", 0)
                # Advance offset past this update so we don't re-process it
                offset = update_id + 1

                # Log the raw update_id for traceability
                logger.debug("Processing Telegram update #%d", update_id)

                # Parse into normalized IncomingMessage
                message = parse_telegram_update(update)
                if message is None:
                    continue

                # Authorization: log user IDs to help the operator whitelist
                if authorized_users:
                    if message.sender_id not in authorized_users:
                        logger.warning(
                            "Unauthorized Telegram user %s (%s) — ignoring. "
                            "Add this ID to TELEGRAM_AUTHORIZED_USERS to allow.",
                            message.sender_id,
                            message.sender_name,
                        )
                        continue
                else:
                    # No whitelist — log IDs so the operator can set one up
                    logger.info(
                        "Message from Telegram user ID: %s (%s)",
                        message.sender_id,
                        message.sender_name,
                    )

                # Dispatch to the Communication Router
                # Each message is handled concurrently so one slow Brain
                # call doesn't delay the next incoming message
                asyncio.create_task(
                    _safe_handle(comm_router, message)
                )

        except asyncio.CancelledError:
            logger.info("Telegram polling cancelled — shutting down")
            break
        except Exception as e:
            logger.error("Telegram polling error: %s — retrying in %ds", e, _RETRY_DELAY)
            await asyncio.sleep(_RETRY_DELAY)


async def _fetch_updates(base_url: str, offset: int | None) -> list[dict]:
    """Call getUpdates and return the list of Update objects.

    Uses long polling (timeout=30). Returns empty list on any error
    so the caller's loop continues cleanly.
    """
    params: dict = {"timeout": _POLL_TIMEOUT, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_POLL_TIMEOUT + 10)  # slightly longer than poll timeout
        ) as client:
            resp = await client.get(f"{base_url}/getUpdates", params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram getUpdates not ok: %s", data)
                await asyncio.sleep(_RETRY_DELAY)
                return []
            return data.get("result", [])

    except httpx.ReadTimeout:
        # Long poll timeout is normal — Telegram returned no updates
        return []
    except httpx.HTTPStatusError as e:
        logger.error("Telegram getUpdates HTTP %s: %s", e.response.status_code, e.response.text[:200])
        await asyncio.sleep(_RETRY_DELAY)
        return []
    except Exception as e:
        logger.error("Telegram getUpdates failed: %s", e)
        await asyncio.sleep(_RETRY_DELAY)
        return []


async def _safe_handle(comm_router, message) -> None:
    """Dispatch a message to the router, catching all exceptions."""
    try:
        await comm_router.handle_incoming(message)
    except Exception as e:
        logger.error(
            "Unhandled exception processing Telegram message %s: %s",
            message.message_id, e, exc_info=True
        )
