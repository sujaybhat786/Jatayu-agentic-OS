"""Knowledge search tool — dispatches to the AnythingLLM plugin.

This tool gives the LLM access to JATAYU's internal knowledge base.
The implementation delegates directly to the plugin manager (no HTTP
self-loop) so it works regardless of what port the server listens on.

The plugin_manager is injected at registration time by Brain.__init__
through the `bind_plugin_manager` helper.
"""

from __future__ import annotations

import logging
from typing import Any

from jatayu.tools import Tool, ToolRegistry, ToolParam

logger = logging.getLogger(__name__)

# Injected by Brain after plugin_manager is ready.
# Using a module-level reference avoids circular imports and keeps the
# tool callable as a plain function (ToolRegistry requires Callable).
_plugin_manager = None


def bind_plugin_manager(plugin_manager) -> None:
    """Inject the PluginManager so execute_search can reach AnythingLLM.

    Called once from Brain._register_tools() after the plugin manager is
    initialized. Safe to call multiple times (last write wins).
    """
    global _plugin_manager
    _plugin_manager = plugin_manager
    logger.info("knowledge_search: PluginManager bound")


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="knowledge_search",
        description=(
            "Search JATAYU's internal organizational knowledge "
            "(Artificial Budhi, projects, people, SOPs, etc.)"
        ),
        params=[
            ToolParam(
                name="query",
                type="string",
                description="The search query.",
                required=True,
            )
        ],
        handler=execute_search,
        requires_confirmation=False,
        category="knowledge",
    ))


def execute_search(query: str, **kwargs: Any) -> str:
    """Search the knowledge base via the AnythingLLM plugin.

    Delegates directly to the plugin instead of making an HTTP call back
    to the running server, eliminating the circular self-HTTP dependency.

    Args:
        query: Natural language search query.

    Returns:
        Search result text or an error message.
    """
    if _plugin_manager is None:
        return (
            "Knowledge search is not available yet — "
            "the plugin manager has not been initialized."
        )

    plugin = _plugin_manager.get("anythingllm")
    if plugin is None:
        return (
            "Knowledge search is not available: "
            "AnythingLLM plugin is not loaded. "
            "Check that AnythingLLM is running and configured."
        )

    try:
        result = plugin.execute("knowledge_search", kwargs={"query": query})

        if isinstance(result, dict):
            status = result.get("status")
            if status == "success":
                data = result.get("data", {})
                return (
                    data.get("response")
                    or data.get("summary")
                    or "Knowledge search returned no content."
                )
            # Plugin returned an error payload
            return result.get("summary", "Knowledge search failed.")

        # Plugin returned a plain string
        return str(result) if result else "Knowledge search returned no results."

    except Exception as e:
        logger.error("knowledge_search failed: %s", e)
        return f"Knowledge search encountered an error: {e}"
