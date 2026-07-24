"""Hermes Agent integration — delegate tasks to the Hermes coding agent.

Connects via the Hermes API Server (OpenAI-compatible HTTP endpoint).
Default: http://127.0.0.1:8642
Optional: HERMES_API_KEY in .env for authenticated access.
"""

from __future__ import annotations

import os

import httpx

from jatayu.tools import Tool, ToolParam, ToolRegistry
from jatayu.pipeline.circuit_breaker import get_breaker

HERMES_BASE = os.getenv("HERMES_URL", "http://127.0.0.1:8642")
breaker = get_breaker("hermes")


# ── Tool Handlers ──


def hermes_ask(prompt: str) -> str:
    """Send a prompt to the Hermes coding agent and get a response."""
    if breaker.is_open():
        return "⚠️ Hermes agent is currently offline/unavailable (circuit open)."

    headers = {"Content-Type": "application/json"}

    api_key = os.getenv("HERMES_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        timeout_cfg = httpx.Timeout(10.0, connect=2.0)
        with httpx.Client(timeout=timeout_cfg) as client:
            # Try OpenAI-compatible chat completions endpoint
            resp = client.post(
                f"{HERMES_BASE}/v1/chat/completions",
                headers=headers,
                json={
                    "model": "hermes",
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            )
            breaker.record_success()

            if resp.status_code == 404:
                # Try alternative endpoint
                resp = client.post(
                    f"{HERMES_BASE}/chat",
                    headers=headers,
                    json={"message": prompt},
                )

            resp.raise_for_status()
            data = resp.json()

        # Parse OpenAI-compatible response
        if "choices" in data:
            choices = data["choices"]
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                return f"🧠 **Hermes says:**\n\n{content}"

        # Parse alternative response format
        if "response" in data:
            return f"🧠 **Hermes says:**\n\n{data['response']}"
        if "message" in data:
            return f"🧠 **Hermes says:**\n\n{data['message']}"

        return f"🧠 Hermes responded: {str(data)[:500]}"

    except httpx.ConnectError:
        return "⚠️ Hermes agent not running — start it with `hermes` or `hermes --tui`"
    except httpx.HTTPStatusError as e:
        return f"⚠️ Hermes error: {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Hermes error: {e}"


def hermes_status() -> str:
    """Check if the Hermes agent is running and responsive."""
    headers = {"Content-Type": "application/json"}

    api_key = os.getenv("HERMES_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=5) as client:
            # Try models endpoint (OpenAI-compatible)
            resp = client.get(
                f"{HERMES_BASE}/v1/models",
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_names = [m.get("id", "unknown") for m in models]
                return f"✅ Hermes is running\n   Models: {', '.join(model_names) if model_names else 'available'}"

            # Try health endpoint
            resp = client.get(f"{HERMES_BASE}/health", headers=headers)
            if resp.status_code == 200:
                return "✅ Hermes is running and healthy"

            return f"⚠️ Hermes responded with status {resp.status_code}"

    except httpx.ConnectError:
        return "❌ Hermes is not running — start it with `hermes` or `hermes --tui`"
    except Exception as e:
        breaker.record_failure()
        return f"⚠️ Could not reach Hermes agent at {HERMES_BASE}: {e}"


# ── Registration ──

def register(registry: ToolRegistry) -> None:
    """Register all Hermes agent tools."""
    registry.register(Tool(
        name="hermes_ask",
        description="Send a coding or development task to the Hermes AI agent. Use when the user asks to delegate a coding question, code review, debugging task, or technical request to Hermes.",
        handler=hermes_ask,
        params=[
            ToolParam(name="prompt", type="string", description="The task or question to send to Hermes"),
        ],
    ))

    registry.register(Tool(
        name="hermes_status",
        description="Check if the Hermes AI agent is running and accessible. Use when the user asks about Hermes status or before delegating a task.",
        handler=hermes_status,
        params=[],
    ))
