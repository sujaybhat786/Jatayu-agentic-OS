"""The brain — conversation loop and model provider seam.

Everything talks to the model through this module. The provider (Gemini)
is behind a thin seam (_run_agent_loop) so it can be swapped without
touching the rest of the harness.

Brain v3 (JATAYU Core):
  • Single streaming call — generate_content_stream() from the FIRST call.
  • Session isolation — per-session history + threading.Lock.
  • on_status param — streams friendly tool-status strings to the UI.
  • model param — cost-routed model per-turn.
  • system_prompt_override — memory injected at server layer, passed in here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

from google import genai
from google.genai import types

from jatayu.config import get_config
from jatayu.tools import ToolRegistry
from jatayu.core.capabilities import CapabilityRegistry  # kept for PluginManager
from jatayu.core.plugin_manager import PluginManager
from jatayu.safety.gates import request_confirmation, check_for_injection
from jatayu.logging import log_tool_call, log_confirmation, log_error, log_event

logger = logging.getLogger(__name__)

# ── History cap: max turns kept in the live window per session ──────────────
MAX_HISTORY_TURNS = 20

# ── Session idle eviction: sessions not used for this long are cleared ───────
SESSION_IDLE_SECONDS = 7200  # 2 hours

# ── Tool name → friendly status message shown while executing ────────────────
_TOOL_STATUS: dict[str, str] = {
    "google_gmail_read":         "Reading your emails...",
    "google_gmail_draft":        "Drafting your email...",
    "google_gmail_send":         "Sending your email...",
    "google_calendar_read":      "Checking your calendar...",
    "google_calendar_create":    "Adding to your calendar...",
    "google_drive_search":       "Searching Drive...",
    "google_drive_upload":       "Uploading to Drive...",
    "google_drive_download":     "Downloading from Drive...",
    "google_drive_move":         "Moving file...",
    "google_drive_share":        "Sharing file...",
    "google_drive_delete":       "Deleting from Drive...",
    "google_docs_create":        "Creating document...",
    "google_docs_read":          "Reading document...",
    "google_docs_edit":          "Editing document...",
    "google_docs_delete":        "Deleting document...",
    "google_sheets_create":      "Creating spreadsheet...",
    "google_sheets_read":        "Reading spreadsheet...",
    "google_sheets_update":      "Updating spreadsheet...",
    "google_sheets_append":      "Appending to spreadsheet...",
    "google_sheets_delete_rows": "Deleting rows...",
    "knowledge_search":          "Searching knowledge vault...",
    "remember":                  "Saving to memory...",
    "remember_entity":           "Saving contact...",
    "get_person":                "Looking up contact...",
    "get_project":               "Looking up project...",
    "set_reminder":              "Setting reminder...",
    "list_reminders":            "Checking reminders...",
    "notion_search":             "Searching Notion...",
    "notion_create_page":        "Creating Notion page...",
    "obsidian_search":           "Searching Obsidian vault...",
    "obsidian_write_note":       "Writing to Obsidian...",
    "hermes_ask":                "Asking Hermes (AI agent)...",
    "openclaw_ask":              "Asking OpenClaw (browser agent)...",
    "telegram_send":             "Sending Telegram message...",
    "add_task":                  "Adding task...",
    "complete_task":             "Completing task...",
}


# ── Per-session state ─────────────────────────────────────────────────────────

@dataclass
class SessionState:
    """Holds the per-session conversation state.

    All mutable state lives here. Access via `brain.send()` which acquires
    the session lock before touching history — ensuring serialisation within
    a session and full parallelism across sessions.
    """
    history: list = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    last_active: float = field(default_factory=time.monotonic)
    session_summary: str = ""   # lightweight summary of evicted old turns
    is_cancelled: bool = False  # Set True when watchdog or /stop cancels this turn


# ── Brain ─────────────────────────────────────────────────────────────────────

class Brain:
    """Manages conversation, tools, memory, and model interaction.

    Usage:
        brain = Brain()
        reply = brain.send("Hello!", session_id="web-abc123", on_chunk=print)
    """

    def __init__(self):
        config = get_config()
        self.client = genai.Client(
            api_key=config["gemini_api_key"],
            http_options=types.HttpOptions(timeout=10000),
        )
        self.model: str = config["model"]
        self._base_system_prompt: str = config["system_prompt"]
        self.assistant_name: str = config["assistant_name"]
        self._kill_switch: bool = config.get("kill_switch", False)

        # ── Per-session state ──────────────────────────────────────────────
        self._sessions: dict[str, SessionState] = {}
        self._sessions_lock = Lock()

        # ── Core infrastructure ──────────────────────────────────────────
        self.events = EventBus()
        self.vault = Vault(config["data_dir"])

        # ── Tool registry ────────────────────────────────────────────────
        self.registry = ToolRegistry()

        # ── Plugin platform (CapabilityRegistry is internal-only, not exposed) ──
        _caps = CapabilityRegistry()
        self.plugin_manager = PluginManager(_caps, self.registry)
        self.plugin_manager.discover_and_load()

        self._register_tools()

        # ── System prompt (base; overridden per-call by server memory inject) ──
        self.system_prompt = self._build_system_prompt()

        log_event("startup", {"model": self.model, "tools": len(self.registry.list_tools())})

    # ------------------------------------------------------------------ #
    #  Tool registration                                                   #
    # ------------------------------------------------------------------ #

    def _register_tools(self) -> None:
        """Register all available tools from tool modules."""
        from jatayu.tools import reminders, drafts, scheduler
        from jatayu.tools import notion, obsidian, knowledge, google_workspace, telegram_tool
        from jatayu.memory import store as memory_store

        reminders.register(self.registry)
        drafts.register(self.registry)
        scheduler.register(self.registry)
        memory_store.register(self.registry)
        knowledge.register(self.registry)
        telegram_tool.register(self.registry)
        notion.register(self.registry)
        obsidian.register(self.registry)
        google_workspace.register(self.registry)

        knowledge.bind_plugin_manager(self.plugin_manager)

    # ------------------------------------------------------------------ #
    #  System prompt                                                       #
    # ------------------------------------------------------------------ #

    def _build_system_prompt(self) -> str:
        """Build the base system prompt with routing card.

        Memory facts are injected at the server layer (load_memory_for_prompt)
        and passed in via system_prompt_override — not loaded here.
        """
        prompt = self._base_system_prompt

        # Routing card — concise tool dispatch rules
        prompt += """

ROUTING CARD (follow strictly):
- URL in message + "analyze / what do they do / summarize" → call hermes_ask with the URL.
- Browser automation / clicking / form filling → openclaw_ask.
- "search my notes / knowledge / vault" → knowledge_search FIRST, answer from result.
- Email/calendar/drive/docs/sheets → the matching google_* tool directly.
  Recipient names pre-resolved in CONTEXT CONTACTS below — do NOT call get_person for them.
- Never call more than one plugin agent per turn unless the user asked for a comparison.
- Destructive actions (delete, send, share) require user confirmation before executing.
"""

        # Entity memory rules
        prompt += (
            "\n\nENTITY MEMORY RULES:"
            "\n- Person mentioned by name/nickname/relation → call get_person FIRST"
            " (UNLESS already in CONTEXT CONTACTS)."
            "\n- Project/client mentioned → call get_project FIRST."
            "\n- New person introduced → call remember_entity type='person'."
            "\n- New project mentioned → call remember_entity type='project'."
            "\n- NEVER create a duplicate. Fuzzy-check first."
        )
        return prompt

    def refresh_memory(self, user_input: str = "") -> None:
        """No-op — memory is now injected at server layer per-request."""
        pass

    # ------------------------------------------------------------------ #
    #  Session management                                                  #
    # ------------------------------------------------------------------ #

    def _get_or_create_session(self, session_id: str) -> SessionState:
        """Return (or create) the session state for `session_id`."""
        with self._sessions_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState()
            session = self._sessions[session_id]
            session.last_active = time.monotonic()
            return session

    def evict_idle_sessions(self) -> int:
        """Remove sessions idle longer than SESSION_IDLE_SECONDS. Returns count."""
        now = time.monotonic()
        to_evict = []
        with self._sessions_lock:
            for sid, state in self._sessions.items():
                if now - state.last_active > SESSION_IDLE_SECONDS:
                    to_evict.append(sid)
            for sid in to_evict:
                del self._sessions[sid]
        if to_evict:
            logger.info("Brain: evicted %d idle session(s): %s", len(to_evict), to_evict)
        return len(to_evict)

    def _trim_history_if_needed(self, session: SessionState) -> None:
        """Cap history at MAX_HISTORY_TURNS. Older turns become a session summary."""
        if len(session.history) <= MAX_HISTORY_TURNS:
            return
        drop_count = len(session.history) // 2
        old_turns = session.history[:drop_count]
        session.history = session.history[drop_count:]

        # Lightweight summary — no LLM, just first 80 chars of each old turn
        snippets = []
        for turn in old_turns:
            if not turn.parts:
                continue
            for part in turn.parts:
                if hasattr(part, "text") and part.text:
                    snippets.append(part.text[:80].replace("\n", " "))
                    break
        if snippets:
            session.session_summary = (
                "Earlier in this session: " + " | ".join(snippets[-5:])
            )

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def send(
        self,
        user_input: str,
        *,
        on_chunk: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        tools_to_expose: list[str] | None = None,
        session_id: str = "default",
        confirm_fn: Callable[[str, dict, str | None], bool | None] | None = None,
        model: str | None = None,
        system_prompt_override: str | None = None,
    ) -> str:
        """Send a user message and stream back a reply.

        Args:
            user_input:             The user's message text.
            on_chunk:               Callback(text) for each streamed text token.
            on_status:              Callback(text) for tool-execution status lines.
            tools_to_expose:        None=all, []=none, [...]=filtered subset.
            session_id:             Per-user/channel history isolation key.
            model:                  Model override (from ModelRouter).
            system_prompt_override: Filtered prompt (from ContextBuilder).

        Returns:
            The complete reply text, or empty string on error.
        """
        session = self._get_or_create_session(session_id)
        session.session_id = session_id

        with session.lock:
            input_with_ctx = user_input
            if session.session_summary:
                input_with_ctx = (
                    f"[Context from earlier: {session.session_summary}]\n\n{user_input}"
                )
                session.session_summary = ""  # consumed once

            initial_history_len = len(session.history)
            session.history.append(
                types.Content(role="user", parts=[types.Part(text=input_with_ctx)])
            )

            effective_model = model or self.model
            effective_prompt = system_prompt_override or self.system_prompt

            try:
                full_reply = self._run_agent_loop(
                    session=session,
                    on_chunk=on_chunk,
                    on_status=on_status,
                    tools_to_expose=tools_to_expose,
                    model=effective_model,
                    system_prompt=effective_prompt,
                    user_input=user_input,
                    confirm_fn=confirm_fn,
                )
                if session and getattr(session, 'is_cancelled', False):
                    session.history = session.history[:initial_history_len]
                self._trim_history_if_needed(session)
                return full_reply

            except KeyboardInterrupt:
                session.history = session.history[:initial_history_len]
                return ""

            except Exception as e:
                session.history = session.history[:initial_history_len]
                error_msg = f"⚠️ Couldn't reach the model: {e}"
                log_error("send", str(e))
                if on_chunk:
                    on_chunk(error_msg)
                return error_msg

    # ------------------------------------------------------------------ #
    #  Agent loop — Phase 1: single streaming call                         #
    # ------------------------------------------------------------------ #

    def _run_agent_loop(
        self,
        session: "SessionState",
        on_chunk: "Callable[[str], None] | None",
        on_status: "Callable[[str], None] | None",
        tools_to_expose: "list[str] | None",
        model: str,
        system_prompt: str,
        user_input: str = "",
        confirm_fn: "Callable[[str, dict, str | None], bool | None] | None" = None,
    ) -> str:
        """Single-stream agent loop — no double-call, no re-issue.

        Retry policy: 503/429 errors get up to 2 retries per iteration
        with 1s/2s exponential backoff.
        """
        max_iterations = 10
        tool_config = self._build_tool_config(tools_to_expose)

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
        )
        if tool_config:
            gen_config.tools = tool_config

        demo_mode = get_config().get("demo_mode", False)
        max_attempts = 1 if demo_mode else 2  # Demo mode: 0 retries (10s max); Normal mode: 1 retry (20.5s max)

        iteration = 0
        latest_tool_errors = []
        previous_function_calls = []

        while iteration < max_iterations:
            iteration += 1
            function_calls: list = []
            text_parts: list[str] = []
            raw_parts: list = []   # for history reconstruction

            # ── Stream with per-iteration retry ───────────────────────────
            stream_attempts = 0
            while stream_attempts < max_attempts:
                stream_attempts += 1
                try:
                    stream = self.client.models.generate_content_stream(
                        model=model,
                        config=gen_config,
                        contents=session.history,
                    )

                    for chunk in stream:
                        if not chunk.candidates:
                            continue
                        candidate = chunk.candidates[0]
                        if not candidate.content or not candidate.content.parts:
                            logger.error(
                                "Empty candidate received. Finish reason: %s. Safety ratings: %s",
                                candidate.finish_reason, candidate.safety_ratings
                            )
                            continue

                        for part in candidate.content.parts:
                            raw_parts.append(part)

                            if hasattr(part, "function_call") and part.function_call:
                                function_calls.append(part.function_call)

                            elif hasattr(part, "text") and part.text:
                                text_parts.append(part.text)
                                # Stream text immediately — only if no function calls yet
                                if not function_calls and on_chunk:
                                    on_chunk(part.text)

                    break  # stream completed successfully — exit retry loop

                except Exception as e:
                    err_str = str(e).lower()
                    is_transient = any(kw in err_str for kw in (
                        "503", "unavailable", "429", "resource_exhausted",
                        "timed out", "timeout", "time out", "readtimeout"
                    ))
                    if is_transient and stream_attempts < max_attempts:
                        wait = 0.5
                        logger.warning(
                            "Brain: transient error iteration=%d attempt=%d/%d "
                            "(retrying in %.1fs): %s", iteration, stream_attempts, max_attempts, wait, e
                        )
                        if on_status:
                            on_status(f"Model busy/timing out, retrying in {wait:.1f}s...")
                        import time as _time
                        _time.sleep(wait)
                        # Clear partials before retry
                        function_calls, text_parts, raw_parts = [], [], []
                        continue
                    # Non-retriable or exhausted
                    logger.warning(
                        "Brain: stream error iteration=%d model=%s: %s",
                        iteration, model, e
                    )
                    raise

            # ── Route on whether we got tool calls or text ─────────────────
            if function_calls:
                if session and session.is_cancelled:
                    logger.warning("Session is cancelled — exiting agent loop before executing tools.")
                    return "Action cancelled."
                # Tool-call turn: execute tools and continue loop to next iteration
                session.history.append(
                    types.Content(role="model", parts=raw_parts)
                )
                response_parts = self._execute_tools(
                    function_calls, on_status=on_status, user_input=user_input, session=session, confirm_fn=confirm_fn
                )
                
                # Extract tool errors to surface them if Gemini fails to summarize
                latest_tool_errors = []
                for p in response_parts:
                    if hasattr(p, "function_response") and p.function_response:
                        res = p.function_response.response.get("result", "")
                        # If the tool result looks like an error, add it to our error list
                        res_str = str(res)
                        if res_str.lower().startswith(("error", "failed", "❌", "400", "404", "500", "exception", "account")):
                            latest_tool_errors.append(res_str)
                        else:
                            # Keep it in case the model returns an empty stream anyway
                            latest_tool_errors.append(res_str)
                
                previous_function_calls = function_calls

                session.history.append(
                    types.Content(role="user", parts=response_parts)
                )
                # Continue loop so next iteration sends tool results back to LLM to synthesize final reply
                continue

            else:
                # Text-reply turn: return the assembled text
                final = "".join(text_parts).strip()
                if not final:
                    logger.error(
                        "Gemini returned an empty stream. Tool history: %s, Prompt size: %d",
                        [fc.name for fc in previous_function_calls] if previous_function_calls else "None",
                        sum(len(str(p)) for p in session.history)
                    )
                    if latest_tool_errors:
                        final = "\n\n".join(latest_tool_errors)
                    else:
                        final = "The model returned an empty response. This might be due to safety filters or context length."
                
                session.history.append(
                    types.Content(role="model", parts=[types.Part(text=final)])
                )
                return final

        stuck_msg = "I got stuck in a loop trying to use tools. Could you rephrase?"
        if on_chunk:
            on_chunk(stuck_msg)
        return stuck_msg

    # ------------------------------------------------------------------ #
    #  Tool execution                                                      #
    # ------------------------------------------------------------------ #

    def _execute_tools(
        self,
        function_calls: list,
        on_status: Callable[[str], None] | None = None,
        user_input: str = "",
        session: SessionState | None = None,
        confirm_fn: Callable[[str, dict, str | None], bool | None] | None = None,
    ) -> list:
        """Execute a batch of tool calls and return FunctionResponse parts."""
        response_parts = []

        if session and session.is_cancelled:
            logger.warning("Session %s is cancelled — aborting tool execution.", getattr(session, 'session_id', 'unknown'))
            return [self._fn_response(fc.name, "Action aborted: session request was cancelled.") for fc in function_calls]

        for fc in function_calls:
            if session and session.is_cancelled:
                logger.warning("Session %s cancelled mid-execution — stopping remaining tool calls.", getattr(session, 'session_id', 'unknown'))
                response_parts.append(self._fn_response(fc.name, "Action aborted: session request was cancelled."))
                continue

            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            # Status streaming
            status_msg = _TOOL_STATUS.get(tool_name, f"Running {tool_name}...")
            if on_status:
                on_status(status_msg)

            # Kill switch
            if self._kill_switch:
                result = "Tools are paused (safe mode is active). I can only talk right now."
                response_parts.append(self._fn_response(tool_name, result))
                continue

            # Idempotency / deduplication check for send/destructive tools
            from jatayu.safety.idempotency import get_idempotency_tracker
            sess_id = getattr(session, 'session_id', 'default') if session else 'default'
            if get_idempotency_tracker().check_and_record(tool_name, sess_id, tool_args):
                result = f"⚠️ Action '{tool_name}' blocked: duplicate send/destructive request detected within 5 minutes."
                response_parts.append(self._fn_response(tool_name, result))
                continue

            # Injection check
            injection_found = False
            for val in tool_args.values():
                warning = check_for_injection(str(val))
                if warning:
                    log_event("injection_detected", {"tool": tool_name, "args": tool_args})
                    response_parts.append(self._fn_response(tool_name, warning))
                    injection_found = True
                    break
            if injection_found:
                continue

            # Confirmation gate (Phase 0 minimal stopgap)
            tool = self.registry.get(tool_name)
            if tool and tool.requires_confirmation:
                approved = request_confirmation(tool_name, tool_args, confirm_fn=confirm_fn)
                log_confirmation(tool_name, tool_args, approved)
                if not approved:
                    result = f"⚠️ Confirmation required: Action '{tool_name}' requires explicit user approval before execution (Phase 6 approval flow pending). Action was NOT sent."
                    get_idempotency_tracker().record_outcome(tool_name, sess_id, tool_args, is_success=False)
                    response_parts.append(self._fn_response(tool_name, result))
                    continue

            # Execute with try/except to catch raw uncaught exceptions
            try:
                result = self.registry.execute(tool_name, tool_args)
                log_tool_call(tool_name, tool_args, result)
                res_str = str(result).strip()
                is_success = not any(res_str.lower().startswith(prefix) for prefix in ("❌", "error:", "error", "failed", "400", "404", "500", "exception"))
            except Exception as e:
                logger.error("Tool '%s' raised uncaught exception: %s", tool_name, e)
                result = f"Error executing {tool_name}: {e}"
                is_success = False

            # Record outcome for idempotency deduplication (clears key if is_success=False)
            get_idempotency_tracker().record_outcome(tool_name, sess_id, tool_args, is_success)

            # Refresh memory if a memory tool ran (with user_input for relevance)
            if tool_name in ("remember", "update_memory", "forget", "remember_entity"):
                self.refresh_memory(user_input=user_input)

            response_parts.append(self._fn_response(tool_name, result))

        return response_parts

    @staticmethod
    def _fn_response(name: str, result: str) -> types.Part:
        """Build a FunctionResponse Part."""
        return types.Part(
            function_response=types.FunctionResponse(
                name=name,
                response={"result": result},
            )
        )

    # ------------------------------------------------------------------ #
    #  Provider seam — tool config builder                                 #
    # ------------------------------------------------------------------ #

    def _build_tool_config(self, tools_to_expose: list[str] | None) -> list | None:
        """Build Gemini tool declarations, optionally filtered.

        None  → all tools
        []    → no tools (pure conversation)
        [...] → specific subset
        """
        if self._kill_switch:
            return None

        declarations = self.registry.to_gemini_declarations()

        if tools_to_expose is not None:
            if len(tools_to_expose) == 0:
                return None
            allowed = set(tools_to_expose)
            declarations = [d for d in declarations if d["name"] in allowed]

        if not declarations:
            return None

        return [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(**d) for d in declarations
            ])
        ]

    @staticmethod
    def _extract_text(parts: list) -> str:
        """Pull plain text out of response parts (kept for compatibility)."""
        texts = []
        for p in parts:
            if hasattr(p, "text") and p.text:
                texts.append(p.text)
        return "".join(texts)
