"""Notion integration — search, read, create, and append to pages.

Uses the Notion REST API (v2022-06-28).
Requires NOTION_API_KEY in .env.
"""

from __future__ import annotations

import json
import os

import httpx

from jatayu.tools import Tool, ToolParam, ToolRegistry

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _is_configured() -> bool:
    return bool(os.getenv("NOTION_API_KEY", "").strip())


def _extract_text_from_block(block: dict) -> str:
    """Extract plain text from a Notion block object."""
    btype = block.get("type", "")
    block_data = block.get(btype, {})

    # Most text blocks have a "rich_text" array
    rich_text = block_data.get("rich_text", [])
    if rich_text:
        text = "".join(rt.get("plain_text", "") for rt in rich_text)
        prefix = ""
        if btype == "heading_1":
            prefix = "# "
        elif btype == "heading_2":
            prefix = "## "
        elif btype == "heading_3":
            prefix = "### "
        elif btype == "bulleted_list_item":
            prefix = "• "
        elif btype == "numbered_list_item":
            prefix = "1. "
        elif btype == "to_do":
            checked = block_data.get("checked", False)
            prefix = "[x] " if checked else "[ ] "
        elif btype == "quote":
            prefix = "> "
        elif btype == "code":
            lang = block_data.get("language", "")
            return f"```{lang}\n{text}\n```"
        return f"{prefix}{text}"

    if btype == "divider":
        return "---"
    if btype == "equation":
        return block_data.get("expression", "")

    return ""


# ── Tool Handlers ──


def notion_search(query: str) -> str:
    """Search Notion pages and databases."""
    if not _is_configured():
        return "⚠️ NOTION_API_KEY not set in .env"

    from jatayu.pipeline.circuit_breaker import get_breaker
    breaker = get_breaker("notion")
    if breaker.is_open():
        return "⚠️ Notion API is currently offline/unavailable (circuit open)."

    try:
        timeout_cfg = httpx.Timeout(5.0, connect=2.0)
        with httpx.Client(timeout=timeout_cfg) as client:
            resp = client.post(
                f"{NOTION_BASE}/search",
                headers=_headers(),
                json={"query": query, "page_size": 10},
            )
            resp.raise_for_status()
            breaker.record_success()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"No results found for '{query}'"

        lines = [f"Found {len(results)} result(s) for '{query}':\n"]
        for r in results:
            obj_type = r.get("object", "page")
            obj_id = r.get("id", "")
            title = ""

            # Extract title from properties
            props = r.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    title_parts = prop.get("title", [])
                    title = "".join(t.get("plain_text", "") for t in title_parts)
                    break

            if not title:
                title = "(Untitled)"

            url = r.get("url", "")
            lines.append(f"  • [{obj_type}] {title}\n    ID: {obj_id}\n    URL: {url}")

        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        return f"⚠️ Notion API error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Notion error: {e}"


def notion_read_page(page_id: str) -> str:
    """Read the full content of a Notion page."""
    if not _is_configured():
        return "⚠️ NOTION_API_KEY not set in .env"

    try:
        with httpx.Client(timeout=15) as client:
            # Get page metadata
            page_resp = client.get(
                f"{NOTION_BASE}/pages/{page_id}",
                headers=_headers(),
            )
            page_resp.raise_for_status()
            page = page_resp.json()

            # Extract title
            title = "(Untitled)"
            for prop in page.get("properties", {}).values():
                if prop.get("type") == "title":
                    parts = prop.get("title", [])
                    title = "".join(t.get("plain_text", "") for t in parts)
                    break

            # Get page content (blocks)
            blocks_resp = client.get(
                f"{NOTION_BASE}/blocks/{page_id}/children",
                headers=_headers(),
                params={"page_size": 100},
            )
            blocks_resp.raise_for_status()
            blocks = blocks_resp.json().get("results", [])

        lines = [f"# {title}\n"]
        for block in blocks:
            text = _extract_text_from_block(block)
            if text:
                lines.append(text)

        return "\n".join(lines) if lines else f"# {title}\n(empty page)"

    except httpx.HTTPStatusError as e:
        return f"⚠️ Notion API error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Notion error: {e}"


def notion_create_page(parent_id: str, title: str, content: str = "") -> str:
    """Create a new page in a Notion database or as a child page."""
    if not _is_configured():
        return "⚠️ NOTION_API_KEY not set in .env"

    # Build request body
    body: dict = {
        "parent": {"database_id": parent_id},
        "properties": {
            "title": {
                "title": [{"text": {"content": title}}]
            }
        },
    }

    # Add content blocks if provided
    if content:
        body["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            }
        ]

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{NOTION_BASE}/pages",
                headers=_headers(),
                json=body,
            )

            # If database_id fails, try as page parent
            if resp.status_code == 400:
                body["parent"] = {"page_id": parent_id}
                resp = client.post(
                    f"{NOTION_BASE}/pages",
                    headers=_headers(),
                    json=body,
                )

            resp.raise_for_status()
            page = resp.json()

        return f"✅ Page created: '{title}'\n   ID: {page['id']}\n   URL: {page.get('url', '')}"

    except httpx.HTTPStatusError as e:
        return f"⚠️ Notion API error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Notion error: {e}"


def notion_append_to_page(page_id: str, content: str) -> str:
    """Append content blocks to an existing Notion page."""
    if not _is_configured():
        return "⚠️ NOTION_API_KEY not set in .env"

    # Split content into paragraphs
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    children = []
    for para in paragraphs:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": para}}]
            },
        })

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.patch(
                f"{NOTION_BASE}/blocks/{page_id}/children",
                headers=_headers(),
                json={"children": children},
            )
            resp.raise_for_status()

        return f"✅ Appended {len(children)} block(s) to page {page_id}"

    except httpx.HTTPStatusError as e:
        return f"⚠️ Notion API error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Notion error: {e}"


# ── Registration ──

def register(registry: ToolRegistry) -> None:
    """Register all Notion tools."""
    registry.register(Tool(
        name="notion_search",
        description="Search Notion for pages and databases by keyword. Use when the user wants to find something in Notion.",
        handler=notion_search,
        params=[
            ToolParam(name="query", type="string", description="The search query"),
        ],
    ))

    registry.register(Tool(
        name="notion_read_page",
        description="Read the full content of a Notion page. Use when the user wants to see what's on a specific Notion page. Requires the page ID (from notion_search results).",
        handler=notion_read_page,
        params=[
            ToolParam(name="page_id", type="string", description="The Notion page ID (UUID format)"),
        ],
    ))

    registry.register(Tool(
        name="notion_create_page",
        description="Create a new page in Notion under a database or parent page. Use when the user wants to add a new note, document, or entry in Notion.",
        handler=notion_create_page,
        params=[
            ToolParam(name="parent_id", type="string", description="The ID of the parent database or page"),
            ToolParam(name="title", type="string", description="Title for the new page"),
            ToolParam(name="content", type="string", description="Initial text content for the page", required=False),
        ],
    ))

    registry.register(Tool(
        name="notion_append_to_page",
        description="Append text content to an existing Notion page. Use when the user wants to add text to an existing page.",
        handler=notion_append_to_page,
        params=[
            ToolParam(name="page_id", type="string", description="The Notion page ID to append to"),
            ToolParam(name="content", type="string", description="Text content to append (separate paragraphs with newlines)"),
        ],
    ))
