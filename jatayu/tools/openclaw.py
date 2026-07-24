"""OpenClaw Agent integration — delegate action tasks to the OpenClaw daemon.

Connects via the OpenClaw Gateway HTTP/WebSocket at 127.0.0.1:18789.
No authentication needed for local connections.
"""

from __future__ import annotations

import json
import os

import httpx

from jatayu.tools import Tool, ToolParam, ToolRegistry

OPENCLAW_BASE = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789")


# ── Tool Handlers ──


def openclaw_ask(task: str) -> str:
    """Send a task to the OpenClaw agent and get the response."""
    from jatayu.pipeline.circuit_breaker import get_breaker
    breaker = get_breaker("openclaw")
    if breaker.is_open():
        return "⚠️ OpenClaw agent is currently offline/unavailable (circuit open)."

    try:
        timeout_cfg = httpx.Timeout(10.0, connect=2.0)
        with httpx.Client(timeout=timeout_cfg) as client:
            # Try the agent/run endpoint
            resp = client.post(
                f"{OPENCLAW_BASE}/api/agent/run",
                headers={"Content-Type": "application/json"},
                json={
                    "message": task,
                    "stream": False,
                },
            )

            if resp.status_code == 404:
                # Try chat endpoint
                resp = client.post(
                    f"{OPENCLAW_BASE}/api/chat",
                    headers={"Content-Type": "application/json"},
                    json={"message": task},
                )

            if resp.status_code == 404:
                # Try v1 completions (some versions use this)
                resp = client.post(
                    f"{OPENCLAW_BASE}/v1/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "messages": [{"role": "user", "content": task}],
                        "stream": False,
                    },
                )

            resp.raise_for_status()
            data = resp.json()

        # Parse response — handle multiple formats
        breaker.record_success()
        if "choices" in data:
            choices = data["choices"]
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content", "")
                return f"🦀 **OpenClaw says:**\n\n{content}"

        if "response" in data:
            return f"🦀 **OpenClaw says:**\n\n{data['response']}"

        if "result" in data:
            return f"🦀 **OpenClaw says:**\n\n{data['result']}"

        if "message" in data:
            return f"🦀 **OpenClaw says:**\n\n{data['message']}"

        if "output" in data:
            return f"🦀 **OpenClaw says:**\n\n{data['output']}"

        return f"🦀 OpenClaw responded: {str(data)[:500]}"

    except Exception as e:
        breaker.record_failure()
        return f"⚠️ Could not reach OpenClaw agent at {OPENCLAW_BASE}: {e}"


def openclaw_status() -> str:
    """Check if the OpenClaw daemon is running and responsive."""
    try:
        with httpx.Client(timeout=5) as client:
            # Try health/status endpoints
            for endpoint in ["/api/status", "/health", "/api/health", "/"]:
                try:
                    resp = client.get(f"{OPENCLAW_BASE}{endpoint}")
                    if resp.status_code == 200:
                        data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                        status = data.get("status", "running")
                        version = data.get("version", "")
                        info = f"✅ OpenClaw is running"
                        if version:
                            info += f" (v{version})"
                        if "models" in data:
                            info += f"\n   Models: {data['models']}"
                        return info
                except Exception:
                    continue

            return "⚠️ OpenClaw is reachable but no status endpoint found"

    except httpx.ConnectError:
        return "❌ OpenClaw is not running — start it with `openclaw agent`"
    except Exception as e:
        return f"⚠️ OpenClaw status check failed: {e}"


# ── Registration ──

def register(registry: ToolRegistry) -> None:
    """Register all OpenClaw agent tools."""
    registry.register(Tool(
        name="openclaw_ask",
        description="Send an action task to the OpenClaw AI agent. Use when the user wants to delegate real-world actions like checking calendars, sending messages, browsing the web, running shell commands, or managing files through OpenClaw.",
        handler=openclaw_ask,
        params=[
            ToolParam(name="task", type="string", description="The action or task to send to OpenClaw"),
        ],
    ))

    registry.register(Tool(
        name="openclaw_status",
        description="Check if the OpenClaw AI agent daemon is running. Use when the user asks about OpenClaw status.",
        handler=openclaw_status,
        params=[],
    ))
