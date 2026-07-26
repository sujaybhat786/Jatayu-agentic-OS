"""Web search / URL research — via Gemini's built-in Google Search grounding.

This replaces Hermes as the web-research path (Phase 5). Hermes itself
(jatayu/plugins/hermes/plugin.py) is left alone and still handles actual
coding-delegation tasks via the local `hermes` CLI, if installed — that's a
separate concern from "search the web" / "summarize this URL", which is what
this module is for.

No new infrastructure needed: this uses the same Gemini API key/account
already configured for the rest of JATAYU (config.yaml / .env), just with
Google Search grounding turned on for this one call.
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import types

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        config = get_config()
        _client = genai.Client(
            api_key=config["gemini_api_key"],
            http_options=types.HttpOptions(timeout=15000),
        )
    return _client


def web_search(query: str) -> str:
    """Search the web (or read/summarize a URL) using Gemini's Google Search grounding."""
    try:
        client = _get_client()
        model = get_config().get("model", "gemini-flash-latest")

        response = client.models.generate_content(
            model=model,
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        text = (response.text or "").strip()
        if not text:
            return "⚠️ Web search returned no result — try rephrasing the question."

        # Best-effort source list. Wrapped defensively: if the grounding
        # metadata shape isn't what we expect, we still return the plain
        # answer rather than failing the whole tool call over a citation.
        sources = []
        try:
            candidate = response.candidates[0]
            chunks = getattr(candidate.grounding_metadata, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    title = getattr(web, "title", "") or web.uri
                    sources.append(f"- {title}: {web.uri}")
        except Exception:
            pass

        if sources:
            unique_sources = list(dict.fromkeys(sources))[:5]  # dedupe, cap at 5
            return text + "\n\nSources:\n" + "\n".join(unique_sources)
        return text

    except Exception as e:
        logger.error("web_search failed: %s", e)
        return f"⚠️ Web search failed: {e}"


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="web_search",
        description=(
            "Search the web for current information, or read/summarize a URL the user shared. "
            "Use for real-time facts, news, 'what is X', 'summarize this link', or anything "
            "requiring up-to-date information beyond what you already know."
        ),
        handler=web_search,
        params=[
            ToolParam(name="query", type="string",
                      description="The search query, question, or URL to look up/summarize"),
        ],
    ))
