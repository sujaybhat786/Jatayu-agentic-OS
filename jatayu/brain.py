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
from enum import Enum
from threading import Lock
from typing import Callable

from google import genai
from google.genai import types

from jatayu.config import get_config
from jatayu.tools import ToolRegistry
from jatayu.core.capabilities import CapabilityRegistry  # kept for PluginManager
from jatayu.core.plugin_manager import PluginManager
from jatayu.core.events import EventBus
from jatayu.core.vault import Vault
from jatayu.safety.gates import request_confirmation, check_for_injection
from jatayu.logging import log_tool_call, log_confirmation, log_error, log_event, log_request_lifecycle

logger = logging.getLogger(__name__)

# ── History cap: max turns kept in the live window per session ──────────────
MAX_HISTORY_TURNS = 20

# ── Session idle eviction: sessions not used for this long are cleared ───────
SESSION_IDLE_SECONDS = 3600  # 1 hour


class RequestState(Enum):
    """Authoritative lifecycle state of a request in JATAYU Core."""
    IDLE = "idle"
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    EXECUTING_TOOL = "executing_tool"
    GENERATING_RESPONSE = "generating_response"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


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
    request_state: RequestState = RequestState.IDLE
    session_id: str = "unknown"
    lifecycle_trace: list[str] = field(default_factory=list)
    tools_called: list[dict] = field(default_factory=list)
    last_tools_called: list[dict] = field(default_factory=list)
    llm_latency_ms: float = 0.0

    def set_state(self, new_state: RequestState, detail: str = "") -> None:
        if self.request_state != new_state:
            old_state = self.request_state
            self.request_state = new_state
            transition = f"{old_state.name}→{new_state.name}"
            self.lifecycle_trace.append(transition)
            logger.info("LIFECYCLE [%s]: %s -> %s %s", self.session_id, old_state.name, new_state.name, f"({detail})" if detail else "")

    def cleanup(self) -> None:
        """Formal cleanup phase guaranteeing clean baseline for future requests."""
        self.last_tools_called = list(self.tools_called)
        self.is_cancelled = False
        self.lifecycle_trace.clear()
        self.tools_called.clear()

        self.llm_latency_ms = 0.0
        try:
            from jatayu.web.server import _pending_ws_confirmations
            for req_id, state in list(_pending_ws_confirmations.items()):
                if state.get("session_id") == self.session_id:
                    state["approved"] = False
                    state["event"].set()
                    _pending_ws_confirmations.pop(req_id, None)
        except ImportError:
            pass
        self.set_state(RequestState.IDLE, "Session cleanup completed")



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
        from jatayu.tools import obsidian, knowledge, google_workspace, telegram_tool, web_search
        from jatayu.memory import store as memory_store

        reminders.register(self.registry)
        drafts.register(self.registry)
        scheduler.register(self.registry)
        memory_store.register(self.registry)
        knowledge.register(self.registry)
        telegram_tool.register(self.registry)
        obsidian.register(self.registry)
        google_workspace.register(self.registry)
        web_search.register(self.registry)

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
- URL in message + "analyze / what do they do / summarize" → call web_search with the URL.
- Current events, facts you're unsure of, or anything needing up-to-date info → call web_search.
- Coding/debugging/dev task explicitly for the Hermes agent → hermes_ask (requires the local Hermes CLI to be installed; if it's not, tell the user plainly rather than pretending it worked).
- Browser automation / clicking / form filling → openclaw_ask.
- "search my notes / knowledge / vault" → knowledge_search FIRST, answer from result.
- Email/calendar/drive/docs/sheets → the matching google_* tool directly.
  Recipient names pre-resolved in CONTEXT CONTACTS below — do NOT call get_person for them.
- Never call more than one plugin agent per turn unless the user asked for a comparison.
- Destructive actions (like delete or share) require user confirmation before executing. Sending emails or Telegram messages MUST be executed immediately without asking for confirmation.
- Reminders: ALWAYS convert relative dates ("tomorrow", "next Monday") to absolute format (YYYY-MM-DD HH:MM) using the current date in CONTEXT BACKGROUND.
"""

        # Entity memory rules (Obsidian)
        prompt += (
            "\n\nENTITY MEMORY RULES (Obsidian):"
            "\n- When user shares personal info, preferences, or facts about themselves → call obsidian_update_me_note"
            "\n- Person mentioned by name/nickname/relation → check CONTEXT CONTACTS. If missing, call get_person. If new, call obsidian_create_person"
            "\n- Project/client mentioned → check CONTEXT PROJECTS. If missing, call get_project. If new, call obsidian_create_project"
            "\n- NEVER create a duplicate. Search or lookup first."
        )
        return prompt

    def _compose_prompt(self, memory_block: str | None = None, context_block: str | None = None) -> str:
        """Single, explicit place where the final system prompt is assembled.
        No string-comparison hacks — this is the only function allowed to
        build `effective_prompt`, and it always knows exactly what's in it."""
        parts = [self.system_prompt]
        if memory_block:
            parts.append(memory_block)
        if context_block:
            parts.append(context_block)
        return "\n\n".join(p for p in parts if p)

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

    def _validate_and_sanitize_history(self, session: SessionState) -> None:
        """Permanent runtime safeguard: validates and repairs conversation history before Gemini calls."""
        if not session or not session.history:
            return

        original_len = len(session.history)
        sanitized = []
        i = 0
        while i < len(session.history):
            turn = session.history[i]
            role = getattr(turn, "role", "")
            parts = getattr(turn, "parts", None) or []

            # Rule 1: Remove empty turns
            if not parts:
                i += 1
                continue

            has_fc = any(hasattr(p, "function_call") and p.function_call for p in parts)
            has_fr = any(hasattr(p, "function_response") and p.function_response for p in parts)

            # Rule 2: Orphaned function response without preceding model function call
            if has_fr:
                if not sanitized or getattr(sanitized[-1], "role", "") != "model":
                    break
                prev_parts = getattr(sanitized[-1], "parts", None) or []
                prev_fc = any(hasattr(p, "function_call") and p.function_call for p in prev_parts)
                if not prev_fc:
                    break

            # Rule 3: Model turn with function call must be followed by user function response
            if role == "model" and has_fc:
                if i + 1 >= len(session.history):
                    # Orphaned function call at the very end of history
                    break
                next_turn = session.history[i + 1]
                next_role = getattr(next_turn, "role", "")
                next_parts = getattr(next_turn, "parts", None) or []
                next_fr = any(hasattr(p, "function_response") and p.function_response for p in next_parts)
                if next_role != "user" or not next_fr:
                    break

            sanitized.append(turn)
            i += 1

        if len(sanitized) != original_len:
            dropped = original_len - len(sanitized)
            logger.warning("History Sanitized: session=%s dropped %d invalid/orphaned turns (was %d, now %d)",
                           getattr(session, "session_id", "unknown"), dropped, original_len, len(sanitized))
            session.history = sanitized

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
        memory_block: str | None = None,
        intent: str | None = None,
    ) -> str:

        """Send a user message and stream back a reply.

        Args:
            user_input:             The user's message text.
            on_chunk:               Callback(text) for each streamed text token.
            on_status:              Callback(text) for tool-execution status lines.
            tools_to_expose:        None=all, []=none, [...]=filtered subset.
            session_id:             Per-user/channel history isolation key.
            model:                  Model override (from ModelRouter).
            memory_block:           Pre-fetched memory context (from MemoryStore.retrieve_for_prompt),
                                     ALWAYS just the memory text — never the base system prompt.
                                     This is the preferred way to inject memory; brain.py always
                                     owns composing it together with the base system prompt.
            system_prompt_override: DEPRECATED — full replacement of the composed prompt, kept only
                                     for callers that truly need to bypass composition entirely.
                                     Prefer memory_block for anything memory-related.

        Returns:
            The complete reply text, or empty string on error.
        """
        session = self._get_or_create_session(session_id)
        session.session_id = session_id

        with session.lock:
            t_start = time.perf_counter()
            # Ensure clean baseline before starting any new request
            session.cleanup()
            session.set_state(RequestState.CREATED, "Request Created")
            logger.info("Request Created: session=%s", session_id)

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
            if system_prompt_override is not None:
                # Explicit full bypass — caller takes total responsibility for the prompt.
                effective_prompt = system_prompt_override
            else:
                if memory_block is None:
                    from jatayu.memory.store import load_memory_for_prompt
                    memory_block = load_memory_for_prompt(user_input)
                effective_prompt = self._compose_prompt(memory_block)

            try:
                session.set_state(RequestState.RUNNING, "Starting agent loop")
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
                    logger.info("Request Cancelled: session=%s (was cancelled during execution)", session_id)
                    session.set_state(RequestState.CANCELLED, "Request Cancelled")
                    session.history = session.history[:initial_history_len]
                else:
                    logger.info("Request Completed: session=%s", session_id)
                    session.set_state(RequestState.COMPLETED, "Request Completed")
                self._trim_history_if_needed(session)
                return full_reply


            except KeyboardInterrupt:
                logger.info("Request Cancelled: session=%s (KeyboardInterrupt)", session_id)
                session.set_state(RequestState.CANCELLED, "KeyboardInterrupt")
                session.history = session.history[:initial_history_len]
                return ""

            except Exception as e:
                logger.info("Request Cancelled: session=%s (Exception: %s)", session_id, e)
                session.set_state(RequestState.CANCELLED, f"Exception: {e}")
                session.history = session.history[:initial_history_len]
                error_msg = f"⚠️ Couldn't reach the model: {e}"
                log_error("send", str(e))
                if on_chunk:
                    on_chunk(error_msg)
                return error_msg
            finally:
                total_ms = (time.perf_counter() - t_start) * 1000
                import uuid
                log_request_lifecycle(
                    request_id=str(uuid.uuid4()),
                    session_id=session_id,
                    intent=intent,

                    model=effective_model,
                    tools_called=list(session.tools_called),
                    lifecycle=list(session.lifecycle_trace),
                    llm_latency_ms=getattr(session, "llm_latency_ms", 0.0),
                    total_ms=total_ms,
                    error=str(session.request_state.name) if session.request_state == RequestState.CANCELLED else None,
                )
                # Guarantee formal cleanup phase runs after every turn
                session.cleanup()


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

            self._validate_and_sanitize_history(session)
            if session and session.request_state != RequestState.WAITING_FOR_CONFIRMATION:
                session.set_state(RequestState.GENERATING_RESPONSE, f"Calling Gemini API (iteration {iteration})")

            last_finish_reason = None
            last_safety_ratings = None

            # ── Stream with per-iteration retry ───────────────────────────
            stream_attempts = 0
            while stream_attempts < max_attempts:
                stream_attempts += 1
                try:
                    llm_start = time.perf_counter()
                    stream = self.client.models.generate_content_stream(
                        model=model,
                        config=gen_config,
                        contents=session.history,
                    )

                    for chunk in stream:
                        if not chunk.candidates:
                            continue
                        candidate = chunk.candidates[0]
                        if candidate.finish_reason:
                            last_finish_reason = candidate.finish_reason
                            last_safety_ratings = candidate.safety_ratings
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

                    if session:
                        session.llm_latency_ms += (time.perf_counter() - llm_start) * 1000
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
                        "Gemini returned an empty stream. Tool history: %s, History size: %d, "
                        "Finish reason: %s, Safety ratings: %s",
                        [fc.name for fc in previous_function_calls] if previous_function_calls else "None",
                        sum(len(str(p)) for p in session.history),
                        last_finish_reason, last_safety_ratings,
                    )
                    if latest_tool_errors:
                        final = "\n\n".join(latest_tool_errors)
                    else:
                        final = "The model returned an empty response. This might be due to safety filters or context length."
                
                session.history.append(
                    types.Content(role="model", parts=[types.Part(text=final)])
                )
                logger.info("Response Generated: session=%s", getattr(session, 'session_id', 'unknown'))
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
                if session:
                    session.set_state(RequestState.WAITING_FOR_CONFIRMATION, f"Waiting for {tool_name}")
                logger.info("Confirmation Requested: %s", tool_name)
                approved = request_confirmation(tool_name, tool_args, confirm_fn=confirm_fn)
                log_confirmation(tool_name, tool_args, approved)
                if approved:
                    logger.info("Confirmation Approved: %s", tool_name)
                    if session:
                        session.set_state(RequestState.EXECUTING_TOOL, f"Executing {tool_name}")
                else:
                    if session:
                        session.set_state(RequestState.RUNNING, f"Rejected {tool_name}")
                    result = f"⚠️ Action '{tool_name}' was not approved. No action was taken."
                    get_idempotency_tracker().record_outcome(tool_name, sess_id, tool_args, is_success=False)
                    response_parts.append(self._fn_response(tool_name, result))
                    continue

            # Execute with try/except to catch raw uncaught exceptions
            if session and session.request_state != RequestState.WAITING_FOR_CONFIRMATION:
                session.set_state(RequestState.EXECUTING_TOOL, f"Executing {tool_name}")
            logger.info("Tool Started: %s", tool_name)
            try:
                result, dur_ms = self.registry.execute_with_timing(tool_name, tool_args)
                logger.info("Tool Completed: %s (%.1fms)", tool_name, dur_ms)
                log_tool_call(tool_name, tool_args, result)
                res_str = str(result).strip()
                is_success = not any(res_str.lower().startswith(prefix) for prefix in ("❌", "error:", "error", "failed", "400", "404", "500", "exception"))
                if session and hasattr(session, "tools_called"):
                    session.tools_called.append({"name": tool_name, "duration_ms": round(dur_ms, 1), "success": is_success})
            except Exception as e:
                logger.info("Tool Completed: %s (with exception)", tool_name)
                logger.error("Tool '%s' raised uncaught exception: %s", tool_name, e)
                result = f"Error executing {tool_name}: {e}"
                is_success = False
                if session and hasattr(session, "tools_called"):
                    session.tools_called.append({"name": tool_name, "duration_ms": 0.0, "success": False})

            # Record outcome for idempotency deduplication (clears key if is_success=False)

            get_idempotency_tracker().record_outcome(tool_name, sess_id, tool_args, is_success)

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


