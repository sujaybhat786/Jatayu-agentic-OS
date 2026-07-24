"""Hermes Agent Plugin — CLI-based integration.

Uses the Hermes CLI (`hermes -z "prompt" --yolo --cli`) instead of the
HTTP API. The CLI is already authenticated, has full tool-calling
capabilities, and doesn't require port discovery or API keys.
"""

import subprocess
import shutil
from jatayu.core.plugin import JatayuPlugin, PluginManifest
from jatayu.core.capabilities import Capability
from jatayu.tools import Tool, ToolParam
from jatayu.core.execution import ExecutionResult


class HermesPlugin(JatayuPlugin):
    """Integrates the Hermes coding agent into JATAYU via CLI."""

    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            id="hermes",
            name="Hermes Agent",
            version="2.0.0",
            author="Jatayu OS",
            description="Delegate coding and desktop tasks to the Hermes AI agent via CLI.",
            supported_capabilities=["delegate_coding", "control_desktop"],
            icon="🧠"
        )

    def _find_hermes(self) -> str | None:
        """Find the hermes CLI binary."""
        return shutil.which("hermes")

    def health(self) -> dict:
        hermes_path = self._find_hermes()
        if hermes_path:
            return {"status": "healthy", "details": f"Hermes CLI found at {hermes_path}"}
        return {"status": "unhealthy", "message": "Hermes CLI not found on PATH."}

    def status(self) -> str:
        return "connected" if self._find_hermes() else "disconnected"

    def execute(self, capability: str, **kwargs) -> ExecutionResult:
        if capability in ["delegate_coding", "control_desktop"]:
            prompt = kwargs.get("prompt", "")
            return self._hermes_ask(prompt)
        return ExecutionResult.error(f"Capability {capability} not supported.")

    def _hermes_ask(self, prompt: str) -> ExecutionResult:
        """Send prompt to Hermes via CLI.
        
        Uses `hermes -z "prompt" --yolo --cli` which:
        - -z: One-shot prompt mode (no interactive chat)
        - --yolo: Auto-approve tool calls (no confirmation prompts)
        - --cli: Force CLI mode (no TUI)
        """
        hermes_path = self._find_hermes()
        if not hermes_path:
            return ExecutionResult.error("Hermes CLI not found. Install Hermes first.", agent_used="hermes")

        try:
            result = subprocess.run(
                [hermes_path, "-z", prompt, "--yolo", "--cli"],
                capture_output=True,
                text=True,
                timeout=10,  # 10s max timeout for task execution
                cwd=None,  # Use current working directory
            )

            output = result.stdout.strip()
            if result.returncode != 0:
                error_output = result.stderr.strip() or output or "Unknown error"
                return ExecutionResult.error(
                    f"Hermes CLI exited with code {result.returncode}: {error_output}",
                    agent_used="hermes"
                )

            if not output:
                output = "Task completed (no output)."

            return ExecutionResult.success(
                summary="Delegated to Hermes",
                data={"reply": output},
                agent_used="hermes",
                capability="delegate_coding"
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult.error("Hermes CLI timed out after 120 seconds.", agent_used="hermes")
        except Exception as e:
            return ExecutionResult.error(str(e), agent_used="hermes")

    def get_capabilities(self) -> list[Capability]:
        return [
            Capability(name="delegate_coding", description="Delegate software engineering tasks", category="engineering", tool_names=["hermes_ask"]),
            Capability(name="control_desktop", description="Automate desktop applications", category="execution", tool_names=["hermes_ask"])
        ]

    def get_tools(self) -> list[Tool]:
        def handler(prompt: str):
            res = self._hermes_ask(prompt)
            if res.status == "success":
                return f"🧠 **Hermes says:**\n\n{res.data['reply']}"
            return f"⚠️ Hermes error: {res.summary}"

        def status_handler():
            if self.status() == "connected":
                return "✅ Hermes is running and healthy"
            return "❌ Hermes CLI not found"

        return [
            Tool(
                name="hermes_ask",
                description="Send a task to the Hermes AI agent. Hermes can create files, folders, write code, and automate desktop tasks.",
                handler=handler,
                params=[ToolParam(name="prompt", type="string", description="The task to send")]
            ),
            Tool(
                name="hermes_status",
                description="Check if Hermes is available.",
                handler=status_handler
            )
        ]
