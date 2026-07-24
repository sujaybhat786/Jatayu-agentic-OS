"""WhatsApp webhook payload parser.

Extracts normalized IncomingMessage and Attachment objects from Meta's
deeply-nested webhook payload structure.

Meta's payload format:
  {
    "entry": [{
      "changes": [{
        "value": {
          "contacts": [{"wa_id": "...", "profile": {"name": "..."}}],
          "messages": [{
            "from": "...",
            "id": "...",
            "timestamp": "...",
            "type": "text|image|audio|video|document|contacts|location",
            "text": {"body": "..."},
            "image": {"id": "...", "mime_type": "..."},
            ...
          }]
        }
      }]
    }]
  }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from jatayu.comms.models import Attachment, IncomingMessage

logger = logging.getLogger(__name__)


def parse_whatsapp_payload(payload: dict) -> list[IncomingMessage]:
    """Parse a Meta WhatsApp webhook payload into normalized messages.

    Handles the deeply-nested structure safely — missing keys return
    empty lists rather than raising exceptions.

    Args:
        payload: The raw JSON body from Meta's webhook POST.

    Returns:
        List of normalized IncomingMessage objects. May be empty if the
        payload contains no processable messages (e.g. status updates).
    """
    messages: list[IncomingMessage] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Build a contact lookup: wa_id → profile name
            contacts_lookup: dict[str, str] = {}
            for contact in value.get("contacts", []):
                wa_id = contact.get("wa_id", "")
                name = contact.get("profile", {}).get("name", "")
                if wa_id:
                    contacts_lookup[wa_id] = name

            # Determine if this is from a group
            metadata = value.get("metadata", {})

            for msg in value.get("messages", []):
                parsed = _parse_single_message(msg, contacts_lookup, metadata)
                if parsed:
                    messages.append(parsed)

    return messages


def _parse_single_message(
    msg: dict,
    contacts_lookup: dict[str, str],
    metadata: dict,
) -> IncomingMessage | None:
    """Parse one WhatsApp message dict into an IncomingMessage.

    Returns None for unrecognized or unparseable message types.
    """
    msg_type = msg.get("type", "")
    sender_id = msg.get("from", "")
    message_id = msg.get("id", "")
    raw_ts = msg.get("timestamp", "")

    if not sender_id or not message_id:
        return None

    # Resolve sender name from contacts
    sender_name = contacts_lookup.get(sender_id, sender_id)

    # Convert Unix timestamp to ISO-8601
    try:
        ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc).isoformat()

    # Detect group vs private
    # WhatsApp group messages include a "group_id" in the context
    context = msg.get("context", {})
    # If the message has a "from" that differs from the display_phone_number,
    # and there's group info, it's a group message
    is_group = "group_id" in msg or context.get("group_id")
    group_id = msg.get("group_id", context.get("group_id"))
    chat_id = group_id if is_group else sender_id
    channel_type = "group" if is_group else "private"

    # Reply-to context
    reply_to_id = context.get("id")

    # Parse content based on message type
    text = ""
    attachments: list[Attachment] = []

    if msg_type == "text":
        text = msg.get("text", {}).get("body", "")

    elif msg_type in ("image", "video", "sticker"):
        media_data = msg.get(msg_type, {})
        att_type = "image" if msg_type in ("image", "sticker") else "video"
        attachments.append(Attachment(
            type=att_type,
            mime=media_data.get("mime_type"),
            media_id=media_data.get("id"),
            metadata={"sha256": media_data.get("sha256", "")},
        ))
        # Images/videos may have a caption
        text = media_data.get("caption", "")

    elif msg_type == "audio":
        audio_data = msg.get("audio", {})
        attachments.append(Attachment(
            type="voice",
            mime=audio_data.get("mime_type", "audio/ogg"),
            media_id=audio_data.get("id"),
            metadata={
                "voice": audio_data.get("voice", False),
                "sha256": audio_data.get("sha256", ""),
            },
        ))

    elif msg_type == "document":
        doc_data = msg.get("document", {})
        attachments.append(Attachment(
            type="document",
            mime=doc_data.get("mime_type"),
            filename=doc_data.get("filename"),
            media_id=doc_data.get("id"),
            metadata={"sha256": doc_data.get("sha256", "")},
        ))
        text = doc_data.get("caption", "")

    elif msg_type == "contacts":
        for contact_item in msg.get("contacts", []):
            name_obj = contact_item.get("name", {})
            full_name = name_obj.get("formatted_name", "")
            phones = contact_item.get("phones", [])
            phone = phones[0].get("phone", "") if phones else ""
            attachments.append(Attachment(
                type="contact",
                metadata={"name": full_name, "phone": phone},
            ))

    elif msg_type == "location":
        loc_data = msg.get("location", {})
        attachments.append(Attachment(
            type="location",
            metadata={
                "lat": loc_data.get("latitude"),
                "lon": loc_data.get("longitude"),
                "name": loc_data.get("name", ""),
                "address": loc_data.get("address", ""),
            },
        ))

    elif msg_type == "reaction":
        # Reactions are not messages — skip
        return None

    elif msg_type == "interactive":
        # Button/list replies
        interactive = msg.get("interactive", {})
        int_type = interactive.get("type", "")
        if int_type == "button_reply":
            text = interactive.get("button_reply", {}).get("title", "")
        elif int_type == "list_reply":
            text = interactive.get("list_reply", {}).get("title", "")

    else:
        logger.warning("Unhandled WhatsApp message type: %s", msg_type)
        return None

    return IncomingMessage(
        source="whatsapp",
        sender_id=sender_id,
        sender_name=sender_name,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        timestamp=ts,
        channel_type=channel_type,
        attachments=attachments,
        reply_to_id=reply_to_id,
        metadata={"whatsapp_type": msg_type},
    )
