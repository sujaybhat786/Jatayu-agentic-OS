"""OpenClaw Agent Plugin."""

import httpx
from jatayu.core.plugin import JatayuPlugin, PluginManifest
from jatayu.core.capabilities import Capability
from jatayu.tools import Tool, ToolParam
from jatayu.core.execution import ExecutionResult

class OpenClawPlugin(JatayuPlugin):
    """Integrates the OpenClaw physical action agent into JATAYU."""
    
    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            id="openclaw",
            name="OpenClaw Agent",
            version="1.0.0",
            author="Jatayu OS",
            description="Delegate real-world physical actions to the OpenClaw agent.",
            supported_capabilities=["delegate_action"],
            icon="🦾"
        )
        
    def _get_base_url(self):
        return "http://127.0.0.1:8643"
        
    def health(self) -> dict:
        try:
            with httpx.Client(timeout=3) as client:
                resp = client.get(f"{self._get_base_url()}/health")
                if resp.status_code == 200:
                    return {"status": "healthy"}
        except Exception:
            pass
        return {"status": "unhealthy", "message": "Could not connect to OpenClaw."}
        
    def status(self) -> str:
        h = self.health()
        return "connected" if h["status"] == "healthy" else "disconnected"

    def execute(self, capability: str, **kwargs) -> ExecutionResult:
        if capability == "delegate_action":
            action = kwargs.get("action", "")
            return self._openclaw_ask(action)
        return ExecutionResult.error(f"Capability {capability} not supported.")
        
    def _openclaw_ask(self, action: str) -> ExecutionResult:
        from jatayu.pipeline.circuit_breaker import get_breaker
        breaker = get_breaker("openclaw")
        if breaker.is_open():
            return ExecutionResult.error("OpenClaw agent is currently offline/unavailable (circuit open).", agent_used="openclaw")
        try:
            timeout_cfg = httpx.Timeout(10.0, connect=2.0)
            with httpx.Client(timeout=timeout_cfg) as client:
                resp = client.post(
                    f"{self._get_base_url()}/action",
                    headers={"Content-Type": "application/json"},
                    json={"intent": action},
                )
                resp.raise_for_status()
                data = resp.json()
                breaker.record_success()
                
            return ExecutionResult.success(
                summary="Delegated to OpenClaw",
                data={"reply": data.get("result", "Action executed.")},
                agent_used="openclaw",
                capability="delegate_action"
            )
        except Exception as e:
            breaker.record_failure()
            return ExecutionResult.error(f"Failed to execute action via OpenClaw: {e}", agent_used="openclaw")

    def get_capabilities(self) -> list[Capability]:
        return [
            Capability(name="delegate_action", description="Delegate general real-world actions", category="execution", tool_names=["openclaw_ask"])
        ]
        
    def get_tools(self) -> list[Tool]:
        def handler(action: str):
            res = self._openclaw_ask(action)
            if res.status == "success":
                return f"🦾 **OpenClaw says:**\n\n{res.data['reply']}"
            return f"⚠️ OpenClaw error: {res.summary}"
            
        return [
            Tool(
                name="openclaw_ask",
                description="Send a physical task to the OpenClaw agent.",
                handler=handler,
                params=[ToolParam(name="action", type="string", description="The action to perform")]
            )
        ]
