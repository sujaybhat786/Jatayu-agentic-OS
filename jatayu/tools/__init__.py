"""Tool registry — register, describe, and execute tools.

Every capability the assistant has beyond talking lives here as a tool.
Adding a new capability means writing one tool function and registering
it — never editing the core loop.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParam:
    """One parameter for a tool."""
    name: str
    type: str            # "string", "integer", "number", "boolean", "array"
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass
class Tool:
    """A registered tool the model can call."""
    name: str
    description: str
    handler: Callable[..., str]
    params: list[ToolParam] = field(default_factory=list)
    requires_confirmation: bool = False
    category: str = "general"


class ToolRegistry:
    """Central registry of all available tools.

    Usage:
        registry = ToolRegistry()
        registry.register(Tool(name="...", description="...", handler=fn, params=[...]))
        declarations = registry.to_gemini_declarations()
        result = registry.execute("tool_name", {"arg": "value"})
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises if the name is already taken."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    # ------------------------------------------------------------------ #
    #  Execution                                                          #
    # ------------------------------------------------------------------ #

    def execute(self, name: str, args: dict[str, Any]) -> str:
        """Run a tool by name with the given arguments.

        Returns:
            A plain-language result string (or error) for the model.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'. Available: {', '.join(self._tools)}"

        try:
            result = tool.handler(**args)
            # Ensure result is always a string
            if not isinstance(result, str):
                result = json.dumps(result, indent=2, default=str)
            return result
        except TypeError as e:
            return f"Error calling {name}: bad arguments — {e}"
        except Exception as e:
            return f"Error running {name}: {e}"

    # ------------------------------------------------------------------ #
    #  Gemini integration                                                 #
    # ------------------------------------------------------------------ #

    def to_gemini_declarations(self) -> list[dict]:
        """Convert all registered tools to Gemini function declarations.

        Returns a list of dicts suitable for passing as `tools` to the
        Gemini API's GenerateContentConfig.
        """
        declarations = []
        for tool in self._tools.values():
            properties = {}
            required = []
            for p in tool.params:
                prop: dict[str, Any] = {
                    "type": p.type.upper(),
                    "description": p.description,
                }
                if p.enum:
                    prop["enum"] = p.enum
                # Gemini requires 'items' for ARRAY types
                if p.type.upper() == "ARRAY":
                    prop["items"] = {"type": "STRING"}
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)

            declarations.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "OBJECT",
                    "properties": properties,
                    "required": required,
                },
            })
        return declarations
