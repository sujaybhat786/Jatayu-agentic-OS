"""Jatayu OS — Web server with WebSocket chat and REST API.

Wraps the existing Brain, tools, and memory into a web interface.
Run with: python -m jatayu.web.server
"""

import logging
import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger("jatayu.server")

# ── Performance debug flag ──
# Set JATAYU_PERF_DEBUG=1 in environment (or debug_mode in config.yaml) to log per-stage timing.
_PERF_DEBUG: bool = os.getenv("JATAYU_PERF_DEBUG", "0").strip() == "1"


def _perf_log(label: str, t0: float, app_state=None) -> float:
    """Log elapsed time since t0 and return current time. No-op unless _PERF_DEBUG."""
    if app_state is not None:
        setattr(app_state, "current_stage", label)
    if _PERF_DEBUG:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logging.getLogger("jatayu.perf").info("[PERF] %-35s %6.1f ms", label, elapsed_ms)
    return time.perf_counter()

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from jatayu.brain import Brain
from jatayu.config import get_config, reset_config
from jatayu.voice.voice_manager import VoiceManager
from jatayu.voice.speech_formatter import format_for_speech
from jatayu.conversation.service import ConversationService

# ── Paths ──
STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = None  # set on startup


def _load_json(filename: str) -> list | dict:
    """Load a JSON data file, return empty list/dict if missing."""
    path = Path(DATA_DIR) / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []



# ── FastAPI app ──
app = FastAPI(title="Jatayu OS", docs_url=None, redoc_url=None)

# Mount Google integrations
from jatayu.integrations.google.auth_routes import router as google_router
app.include_router(google_router)


@app.middleware("http")
async def no_cache(request, call_next):
    """Disable caching for static files during development."""
    response = await call_next(request)
    if "/static/" in str(request.url):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response



from fastapi.staticfiles import StaticFiles

class NoCacheStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False
        
    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


# Brain instance (created on startup)
brain: Brain | None = None
# Voice manager — OpenAI Whisper STT (initialised on startup)
_voice_manager: VoiceManager | None = None


@app.on_event("startup")
async def startup():
    global brain, DATA_DIR, _voice_manager
    reset_config()
    config = get_config()
    DATA_DIR = config["data_dir"]
    brain = Brain()
    _voice_manager = VoiceManager()

    # Initialize Conversation Service
    db_path = Path(DATA_DIR) / "conversations.db"
    conv_service = ConversationService(str(db_path), brain.events)
    app.state.history = conv_service

    # ── Build Pipeline Services ──────────────────────────────────────────
    pipeline = _build_pipeline(DATA_DIR, brain, conv_service)
    app.state.pipeline = pipeline

    # ── Phase 2: Command Center (Lane 0 fast path) ───────────────────────
    from jatayu.pipeline.command_center import CommandCenter
    app.state.command_center = CommandCenter(brain_instance=brain)

    # ── Phase 4: Cost Ledger ─────────────────────────────────────────────
    from jatayu.pipeline.cost_ledger import CostLedger
    app.state.cost_ledger = CostLedger(data_dir=DATA_DIR)

    # ── Phase 6: AnythingLLM circuit breaker ─────────────────────────────
    from jatayu.pipeline.circuit_breaker import get_breaker
    app.state.anythingllm_breaker = get_breaker(
        "anythingllm", failure_threshold=3, reset_seconds=300
    )

    # ── Communication Layer (messaging only — Voice stays independent) ──
    await _init_communication_layer(brain, _voice_manager, config, conv_service, pipeline)


def _build_pipeline(data_dir: str, brain_instance, conv_service) -> dict:
    """Build core pipeline services for JATAYU Core.

    Keeps only the services actively used in the Core request path:
    EventLog, IntentClassifier, CommandCenter, CostLedger.
    All workspace/graph/planner/propagation services live in the labs branch.
    """
    import logging
    _log = logging.getLogger("jatayu.pipeline.startup")
    services: dict = {}

    try:
        from jatayu.pipeline.event_log import EventLog
        services["event_log"] = EventLog(data_dir)
        _log.info("Pipeline: EventLog ready")
    except Exception as exc:
        _log.error("Pipeline: EventLog failed: %s", exc)
        services["event_log"] = None

    try:
        from jatayu.pipeline.intent_classifier import IntentClassifier
        services["intent_classifier"] = IntentClassifier()
        _log.info("Pipeline: IntentClassifier ready")
    except Exception as exc:
        _log.error("Pipeline: IntentClassifier failed: %s", exc)
        services["intent_classifier"] = None

    try:
        from jatayu.context import DailyContextService
        services["daily_context"] = DailyContextService()
        _log.info("Pipeline: DailyContextService ready")
    except Exception as exc:
        _log.error("Pipeline: DailyContextService failed: %s", exc)
        services["daily_context"] = None

    active = sum(1 for v in services.values() if v is not None)
    _log.info("Pipeline: %d/%d services active", active, len(services))
    return services



async def _init_communication_layer(brain_instance, voice_mgr, config, conv_service, pipeline: dict | None = None):
    """Initialize the Communication Layer — Telegram only for JATAYU Core.

    Voice interactions are INDEPENDENT and never touch this layer.
    """
    from jatayu.comms.dispatcher import RequestDispatcher
    from jatayu.comms.registry import ProviderRegistry
    from jatayu.comms.session import SessionManager
    from jatayu.comms.router import CommunicationRouter

    p = pipeline or {}
    dispatcher = RequestDispatcher(
        brain_instance,
        conv_service=conv_service,
        intent_classifier=p.get("intent_classifier"),
        event_log=p.get("event_log"),
    )
    app.state.dispatcher = dispatcher
    provider_registry = ProviderRegistry()
    session_mgr = SessionManager()

    # authorized_users is per-provider, sourced from env vars
    # Format: TELEGRAM_AUTHORIZED_USERS=123456789,987654321
    authorized_users: dict[str, list[str]] = {}

    # ── Telegram (Primary) ──
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_polling_task = None
    if tg_token:
        try:
            from jatayu.comms.telegram.adapter import TelegramAdapter
            from jatayu.comms.telegram.polling import start_telegram_polling

            tg_adapter = TelegramAdapter(tg_token)
            provider_registry.register(tg_adapter)

            # Authorized users from env var (comma-separated Telegram user IDs)
            tg_users_raw = os.getenv("TELEGRAM_AUTHORIZED_USERS", "").strip()
            tg_users = [u.strip() for u in tg_users_raw.split(",") if u.strip()] if tg_users_raw else []
            if tg_users:
                authorized_users["telegram"] = tg_users

            logger.info("Telegram provider registered")
            if tg_users:
                logger.info("Telegram authorized user IDs: %s", tg_users)
            else:
                logger.info("No TELEGRAM_AUTHORIZED_USERS set — will log user IDs on first message")

        except Exception as e:
            logger.exception("Telegram init failed: %s", e)
    else:
        logger.info("Telegram not configured (no TELEGRAM_BOT_TOKEN)")

    # ── Build the Communication Router ──
    if len(provider_registry) == 0:
        logger.info("No messaging providers configured — Communication Layer idle")
        return

    comm_router = CommunicationRouter(
        dispatcher=dispatcher,
        registry=provider_registry,
        session_manager=session_mgr,
        voice_manager=voice_mgr,
        authorized_users=authorized_users,
    )

    # ── Start Telegram long polling as an asyncio background task ──
    if tg_token and "telegram" in provider_registry:
        tg_users = authorized_users.get("telegram", [])
        tg_polling_task = asyncio.create_task(
            start_telegram_polling(tg_token, comm_router, authorized_users=tg_users or None)
        )
        app.state.tg_polling_task = tg_polling_task
        logger.info("Telegram long polling task started")

    logger.info("Communication Layer active — providers: %s", provider_registry.list_providers())




@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    with open(STATIC_DIR / "index.html", "rb") as f:
        html = f.read()
    return Response(
        content=html, 
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


# ── REST API for conversations ──

@app.get("/api/conversations")
async def get_conversations(limit: int = 50, offset: int = 0):
    if not hasattr(app.state, "history"):
        return {"conversations": []}
    convs = app.state.history.list_conversations(limit, offset)
    return {"conversations": [c.__dict__ for c in convs]}


# ── Workspace endpoints removed in JATAYU Core (moved to labs branch) ──






@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    if not hasattr(app.state, "history"):
        return {"error": "History service not available"}
    data = app.state.history.get_conversation(conv_id)
    if not data:
        return {"error": "Conversation not found"}
    return {
        "conversation": data["conversation"].__dict__,
        "messages": [m.__dict__ for m in data["messages"]]
    }

@app.post("/api/conversations")
async def create_conversation():
    if not hasattr(app.state, "history"):
        return {"error": "History service not available"}
    conv_id = app.state.history.create_conversation()
    return {"conversation_id": conv_id}

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    if not hasattr(app.state, "history"):
        return {"error": "History service not available"}
    deleted = app.state.history.delete_conversation(conv_id)
    return {"success": deleted}


# ── REST API for panels ──

@app.get("/api/reminders")
async def get_reminders():
    data = _load_json("reminders.json")
    active = [r for r in data if not r.get("done")]
    return {"reminders": active}


@app.get("/api/schedule")
async def get_schedule():
    from datetime import date
    data = _load_json("schedule.json")
    if isinstance(data, dict) and data.get("date") == str(date.today()):
        return {"date": data["date"], "tasks": data.get("tasks", [])}
    return {"date": str(date.today()), "tasks": []}


@app.get("/api/drafts")
async def get_drafts():
    return {"drafts": _load_json("drafts.json")}


@app.get("/api/memory")
async def get_memory():
    return {"memories": _load_json("memory.json")}


@app.get("/api/status")
async def get_status():
    config = get_config()
    from jatayu.pipeline.circuit_breaker import all_statuses
    return {
        "name": config["assistant_name"],
        "model": config["model"],
        "kill_switch": config.get("kill_switch", False),
        "tools": len(brain.registry.list_tools()) if brain else 0,
        "status": "optimal",
        "circuit_breakers": all_statuses(),
    }


@app.get("/api/cost-today")
async def get_cost_today():
    """Phase 4: Daily cost summary — token spend, estimated USD, cap utilization."""
    ledger = getattr(app.state, "cost_ledger", None)
    if not ledger:
        return {"error": "Cost ledger not initialized"}
    return ledger.today_summary()


@app.get("/api/system-health")
async def get_system_health():
    """Core system health endpoint."""
    from jatayu.tools.obsidian import _is_running as obsidian_running
    return {
        "status": "online",
        "version": "1.0-core",
        "brain_status": "optimal" if brain else "offline",
        "obsidian_sync_status": "connected" if obsidian_running() else "offline",
    }





@app.get("/api/plugins")
async def get_plugins():
    """Return all discovered and loaded plugins."""
    if not brain:
        return {}
    return brain.plugin_manager.to_dict()

@app.post("/api/plugins/{plugin_id}/execute")
async def execute_plugin_action(plugin_id: str, request: Request):
    """Execute an action on a specific plugin."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    
    body = await request.json()
    action = body.get("action")
    kwargs = body.get("kwargs", {})
    
    if not action:
        raise HTTPException(status_code=400, detail="Action is required")
        
    plugin = brain.plugin_manager.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found")
    result = plugin.execute(action, **kwargs)
    return {
        "status": result.status,
        "summary": result.summary,
        "artifacts": result.artifacts,
        "data": result.data,
        "errors": result.errors
    }


@app.get("/api/credentials")
async def get_credentials():
    """Return the list of configured credentials (keys only)."""
    if not brain:
        return {}
    vault_data = brain.vault._load()
    # Strip values for security, return only boolean existence flags
    return {p_id: {k: True for k in creds.keys()} for p_id, creds in vault_data.items()}


# ── Voice API endpoints ──

@app.post("/api/transcribe")
async def transcribe_audio(request: Request):
    """Receive audio from the browser mic, transcribe via OpenAI Whisper.

    Accepts raw audio bytes (webm/opus from MediaRecorder).
    Returns JSON with the transcript.
    """
    audio_bytes = await request.body()
    content_type = request.headers.get("content-type", "audio/webm")

    if not audio_bytes:
        return {"transcript": "", "error": "No audio data received"}

    if not _voice_manager:
        return {"transcript": "", "error": "Voice manager not initialised"}

    try:
        # Run synchronous Whisper call in a thread so we don't block the event loop
        loop = asyncio.get_running_loop()
        transcript = await loop.run_in_executor(
            None,
            lambda: _voice_manager.transcribe(audio_bytes, content_type)
        )
        return {"transcript": transcript}
    except Exception as e:
        return {"transcript": "", "error": str(e)}


@app.post("/api/speak")
async def speak_text(request: Request):

    """Convert text to speech via ElevenLabs, return MP3 audio.

    Accepts JSON: {"text": "..."}.
    Returns audio/mpeg bytes for browser playback.
    """
    body = await request.json()
    text = body.get("text", "").strip()

    if not text:
        return Response(content=b"", media_type="audio/mpeg")

    # Speech Formatter: transform written response into natural spoken text.
    # The written response in Chat is NEVER modified — only what ElevenLabs hears.
    text = format_for_speech(text)

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return Response(content=b"", media_type="audio/mpeg")

    # Voice ID map — includes custom cloned voices
    voice_map = {
        "5th veda narrator": "Z54DWF9BDNEs2qFuPPMf",
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam": "pNInz6obpgDQGcFmaJgB",
        "josh": "TxGEqnHWrfWFTfGW9XjX",
        "george": "JBFqnCBsd6RMkjVDRZzb",
        "brian": "nPczCjzI2devNBz1zQrb",
        "loki": "S4szcWHblYGUodN1DoSR",
    }
    config = get_config()
    voice_name = config.get("elevenlabs_voice", "5th veda narrator").lower()
    voice_id = voice_map.get(voice_name, voice_map["5th veda narrator"])

    try:
        from fastapi.responses import StreamingResponse

        async def audio_stream_generator():
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?optimize_streaming_latency=4",
                        headers={
                            "xi-api-key": api_key,
                            "Content-Type": "application/json",
                            "Accept": "audio/mpeg",
                        },
                        json={
                            "text": text,
                            "model_id": "eleven_flash_v2_5",
                            "voice_settings": {
                                "stability": 0.5,
                                "similarity_boost": 0.75,
                            },
                        },
                        timeout=60.0,
                    ) as resp:
                        if resp.status_code != 200:
                            error_body = (await resp.aread()).decode("utf-8", errors="ignore")[:300]
                            logger.error("ElevenLabs TTS HTTP %s: %s", resp.status_code, error_body)
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except Exception as e:
                logger.error("TTS stream error: %s", e)

        return StreamingResponse(audio_stream_generator(), media_type="audio/mpeg")

    except Exception as e:
        logger.error("TTS error: %s", e)
        return Response(
            content=b"",
            media_type="audio/mpeg",
            headers={"X-TTS-Error": str(e)[:200]},
        )


# ── Chief of Staff / Workspace endpoints removed in JATAYU Core (labs branch) ──


_pending_ws_confirmations: dict[str, dict] = {}

# ── WebSocket chat ──

@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            # Handle WebSocket confirmation response from Web UI
            if msg.get("type") == "confirm_response":
                req_id = msg.get("request_id")
                approved = bool(msg.get("approved", False))
                pending = _pending_ws_confirmations.get(req_id)
                if pending:
                    pending["approved"] = approved
                    pending["event"].set()
                continue

            user_text = msg.get("text", "").strip()
            conv_id = msg.get("conversation_id")

            if not user_text:
                continue

            history = getattr(app.state, "history", None)
            if history:
                if not conv_id:
                    clean_text = user_text.strip()
                    title = clean_text[:47] + ("..." if len(clean_text) > 47 else "")
                    conv_id = history.create_conversation(title=title, provider="dashboard")
                try:
                    # Detect entity mentions to set context_tag
                    context_tag = None
                    try:
                        from jatayu.memory.entities import detect_entities_in_text
                        matched = detect_entities_in_text(user_text)
                        if matched:
                            # Tag with the first matched entity
                            e = matched[0]
                            context_tag = f"{e['type']}:{e['id']}"
                    except Exception:
                        pass
                    history.append_message(conv_id, role="user", content=user_text, provider="dashboard", context_tag=context_tag)
                except Exception:
                    pass


            # ── Phase 3: Session ID ──────────────────────────────────────
            session_id = f"ws:{conv_id}" if conv_id else "ws:default"

            # Run brain in a thread (it's synchronous)
            loop = asyncio.get_running_loop()
            chunks_queue: asyncio.Queue = asyncio.Queue()

            def ws_confirmation_gate(tool_name, args, desc):
                import threading
                req_id = str(uuid.uuid4())
                evt = threading.Event()
                state = {"event": evt, "approved": False, "session_id": session_id}
                _pending_ws_confirmations[req_id] = state

                def _dispatch_confirm_request():
                    asyncio.create_task(ws.send_json({
                        "type": "confirm_request",
                        "tool": tool_name,
                        "args": args,
                        "description": desc,
                        "request_id": req_id,
                    }))
                loop.call_soon_threadsafe(_dispatch_confirm_request)

                try:
                    if evt.wait(timeout=60.0):
                        return state["approved"]
                    else:
                        import logging as _l
                        _l.getLogger("jatayu.server").warning(
                            "WS confirmation gate timed out for %s", tool_name
                        )
                        return False
                finally:
                    _pending_ws_confirmations.pop(req_id, None)


            def on_chunk(text: str):
                """Called from the brain thread for each streamed chunk."""
                loop.call_soon_threadsafe(chunks_queue.put_nowait, text)

            def on_status(text: str):
                """Called from the brain thread with tool-execution status."""
                loop.call_soon_threadsafe(
                    chunks_queue.put_nowait,
                    f"\x00STATUS\x00{text}"  # sentinel prefix — stripped by chunk drain
                )

            async def run_brain():
                """Run the brain in a thread and stream chunks via WebSocket.

                Performance optimisations applied here:
                  1. Knowledge pre-fetch is INTENT-GATED — only runs for
                     research/search/unknown intents, never for conversation.
                  2. Pre-fetch runs in run_in_executor so it never blocks
                     the event loop.
                  3. Redundant memory load removed (brain.py already loads it).
                  4. tools_to_expose passed to brain.send() for intent-filtered
                     tool exposure.
                  5. Panel data only refreshed after state-changing intents.
                  6. Per-stage timing logged when JATAYU_PERF_DEBUG=1.
                """
                _t_start = time.perf_counter()
                _t = _t_start

                # ── STAGE 1: Intent Classification (in-memory, < 1 ms) ──────────
                intent_result = None
                tools_to_expose = None
                needs_knowledge = True

                intent_classifier = getattr(app.state, "pipeline", {}).get("intent_classifier")
                if intent_classifier:
                    try:
                        intent_result = intent_classifier.classify(user_text)
                        _knowledge_intents = {"research", "search", "unknown"}
                        needs_knowledge = intent_result.intent in _knowledge_intents
                        from jatayu.pipeline.intent_classifier import INTENT_TOOL_GROUPS
                        tools_to_expose = INTENT_TOOL_GROUPS.get(intent_result.intent)
                    except Exception:
                        pass

                _t = _perf_log("Stage 1: Intent classification", _t_start, app.state)

                # ── STAGE 1b: Command Center — Lane 0 fast path ──────────────────
                # Handles greetings, slash commands, direct tool reads, session cache.
                # Returns instantly with no LLM call. Falls through to Brain if None.
                command_center = getattr(app.state, "command_center", None)
                fast_result = None
                if command_center:
                    try:
                        fast_result = command_center.dispatch(
                            text=user_text,
                            session_id=session_id,
                            intent=intent_result.intent if intent_result else None,
                        )
                    except Exception:
                        pass

                if fast_result:
                    # ── Lane 0: respond immediately ──────────────────────────────
                    reply_text = fast_result.text

                    # Resolve /brief sentinel — brief service removed in Core
                    if reply_text == "__SLASH_BRIEF__":
                        reply_text = "Daily brief is not available in JATAYU Core."

                    done_payload = {
                        "type": "done", "text": reply_text,
                        "conversation_id": conv_id,
                        "lane": 0, "source": fast_result.source,
                    }
                    if _PERF_DEBUG:
                        done_payload["_perf_ms"] = round(
                            (time.perf_counter() - _t_start) * 1000, 1
                        )
                    await ws.send_json(done_payload)
                    if history and conv_id:
                        history.append_message(
                            conv_id, role="assistant", content=reply_text,
                            status="complete", provider="dashboard"
                        )
                    return   # done — no Brain needed

                _t = _perf_log("Stage 1b: Command center check", _t_start, app.state)

                # ── STAGE 2: Memory inject (direct, no LLM call) ─────────────────
                # Load relevant facts from memory.json for the system prompt.
                # Protected facts (identity, preferences) always included.
                from jatayu.memory.store import load_memory_for_prompt
                memory_block = load_memory_for_prompt(user_text)

                _t = _perf_log("Stage 2: Memory inject", _t_start, app.state)

                # ── STAGE 3: Prompt construction ────────────────────────────────
                # NOTE: we pass the raw memory_block only. brain.py's _compose_prompt()
                # is the single place that assembles base prompt + memory — no more
                # baking brain.system_prompt in here and relying on a string-match
                # check downstream to avoid double-inclusion.
                enhanced_prompt = user_text

                _t = _perf_log("Stage 3: Prompt construction", _t_start, app.state)

                # ── STAGE 3b: Model Routing ──────────────────────────────────────
                selected_model = None
                model_router = getattr(app.state, "pipeline", {}).get("model_router")
                cost_ledger = getattr(app.state, "cost_ledger", None)

                if intent_result:
                    try:
                        # Read the model directly from config.yaml model_routing table
                        # (avoids constructing AgentInfo which requires 9 required fields)
                        from jatayu.config import get_config as _gc
                        _routing = _gc().get("model_routing", {})
                        selected_model = (
                            _routing.get(intent_result.intent)
                            or _routing.get("default")
                            or _gc().get("model", "gemini-3.5-flash")
                        )

                        # Budget guard: downgrade Pro → Flash if soft cap exceeded
                        if cost_ledger and cost_ledger.should_downgrade(intent_result.intent):
                            selected_model = "gemini-3.5-flash"

                    except Exception as _e:
                        import logging as _log
                        _log.getLogger("jatayu.server").warning(
                            "Model routing failed, using default: %s", _e
                        )

                _t = _perf_log("Stage 3b: Model routing", _t_start, app.state)

                # ── STAGE 5: Brain call (thread) + streaming ────────────────────
                def brain_call():
                    return brain.send(
                        enhanced_prompt,
                        on_chunk=on_chunk,
                        on_status=on_status,
                        tools_to_expose=tools_to_expose,
                        session_id=session_id,
                        confirm_fn=ws_confirmation_gate,
                        model=selected_model,
                        memory_block=memory_block,
                        intent=intent_result.intent if intent_result else None,
                    )


                # Start brain in thread
                future = loop.run_in_executor(None, brain_call)

                # Drain the chunk queue and forward chunks to WebSocket
                full_text = []
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            chunks_queue.get(), timeout=0.1
                        )
                        # Detect status sentinel (from on_status callback)
                        if chunk.startswith("\x00STATUS\x00"):
                            status_text = chunk[len("\x00STATUS\x00"):]
                            await ws.send_json({"type": "status", "text": status_text})
                        else:
                            full_text.append(chunk)
                            await ws.send_json({"type": "chunk", "text": chunk})
                    except asyncio.TimeoutError:
                        if future.done():
                            while not chunks_queue.empty():
                                chunk = chunks_queue.get_nowait()
                                if chunk.startswith("\x00STATUS\x00"):
                                    status_text = chunk[len("\x00STATUS\x00"):]
                                    await ws.send_json({"type": "status", "text": status_text})
                                else:
                                    full_text.append(chunk)
                                    await ws.send_json({"type": "chunk", "text": chunk})
                            break

                reply = future.result()
                combined_text = (reply or "".join(full_text)).strip()
                if not combined_text:
                    combined_text = "The action was not completed or confirmed. Please try again."

                _t = _perf_log("Stage 5: Brain + LLM call", _t_start, app.state)

                # ── Phase 4: Record cost ──────────────────────────────────────────
                if cost_ledger:
                    try:
                        # Gemini returns usage_metadata on the response object;
                        # we approximate from text length if metadata unavailable.
                        tok_in  = len(enhanced_prompt.split()) * 1  # rough
                        tok_out = len(combined_text.split()) * 1
                        cost_ledger.record(
                            session_id=session_id,
                            model=selected_model or brain.model,
                            tokens_in=tok_in,
                            tokens_out=tok_out,
                            intent=intent_result.intent if intent_result else "unknown",
                        )
                    except Exception as e:
                        import logging as _log
                        _log.getLogger("jatayu.server").error("Cost tracking failed: %s", e)

                # ── STAGE 5b: Done ───────────────────────────────────────────────
                # brain.send() returns an error message if Gemini is unreachable;
                # send it directly — no offline router fallback in JATAYU Core.
                done_payload: dict = {"type": "done", "text": combined_text, "conversation_id": conv_id}
                if _PERF_DEBUG:
                    total_ms = round((time.perf_counter() - _t_start) * 1000, 1)
                    done_payload["_perf_ms"] = total_ms
                    if intent_result:
                        done_payload["_intent"] = intent_result.intent
                    if selected_model:
                        done_payload["_model"] = selected_model
                await ws.send_json(done_payload)
                if history and conv_id:
                    history.append_message(conv_id, role="assistant", content=combined_text, status="complete", provider="dashboard")

                # Phase 2: Populate session cache with this reply
                if command_center and intent_result:
                    _non_cache_intents = {
                        "email", "calendar", "memory", "reminder",
                        "task_management", "document", "spreadsheet", "meeting",
                    }
                    if intent_result.intent not in _non_cache_intents:
                        command_center.cache_store_reply(session_id, user_text, combined_text)

                _t = _perf_log("Stage 6: Response delivery", _t_start, app.state)


                # ── STAGE 7: Panel refresh (conditional) ─────────────────────────
                _state_changing_intents = {
                    "reminder", "calendar", "memory", "task_management",
                    "document", "spreadsheet", "email", "meeting",
                }
                _should_refresh_panels = (
                    intent_result is None
                    or intent_result.intent in _state_changing_intents
                    or intent_result.intent == "unknown"
                    or any(kw in combined_text for kw in ("✅", "saved", "created", "scheduled", "updated"))
                )

                if _should_refresh_panels:
                    await ws.send_json({
                        "type": "panels",
                        "reminders": (await get_reminders())["reminders"],
                        "schedule": (await get_schedule()),
                        "drafts": (await get_drafts())["drafts"],
                        "memory": (await get_memory())["memories"],
                    })

                _perf_log("Stage 7: Panel refresh", _t_start, app.state)

            demo_mode = get_config().get("demo_mode", False)
            watchdog_limit = 12.0 if demo_mode else 25.0
            try:
                brain_task = asyncio.create_task(run_brain())
                elapsed = 0.0
                poll_interval = 0.5
                while not brain_task.done():
                    await asyncio.sleep(poll_interval)
                    # Operate watchdog based on authoritative request state rather than timers or maps
                    session_obj = brain._sessions.get(session_id)
                    req_state = getattr(session_obj, "request_state", None) if session_obj else None
                    if req_state and getattr(req_state, "name", "") == "WAITING_FOR_CONFIRMATION":
                        elapsed = 0.0  # Reset elapsed while waiting for user confirmation
                    else:
                        elapsed += poll_interval
                    
                    if elapsed > watchdog_limit:
                        logger.warning(
                            "Watchdog triggered: session=%s elapsed=%.1fs limit=%.1fs state=%s",
                            session_id, elapsed, watchdog_limit,
                            getattr(req_state, "name", "unknown") if req_state else "unknown"
                        )
                        brain_task.cancel()
                        raise asyncio.TimeoutError()
                
                # Re-raise any exceptions that occurred inside run_brain
                brain_task.result()
            except asyncio.TimeoutError:
                # Mark session as cancelled so background thread aborts tool execution
                session_obj = brain._sessions.get(session_id)
                if session_obj:
                    session_obj.is_cancelled = True
                    if hasattr(session_obj, "set_state"):
                        from jatayu.brain import RequestState
                        session_obj.set_state(RequestState.CANCELLED, "Watchdog Timeout")

                last_stage = getattr(app.state, "current_stage", "unknown")
                logger.error(
                    "ALERT Watchdog: Session %s timed out after %.1fs at stage '%s'. Prompt: %s",
                    session_id, watchdog_limit, last_stage, user_text[:60]
                )
                await ws.send_json({
                    "type": "done",
                    "text": f"⚠️ Request timed out after {watchdog_limit:.0f}s at stage '{last_stage}'.",
                    "conversation_id": conv_id
                })

    except WebSocketDisconnect:
        # Cancel any pending confirmation futures immediately on disconnect (fail closed)
        for req_id, pending in list(_pending_ws_confirmations.items()):
            pending["approved"] = False
            pending["event"].set()
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ── Entry point ──

def main():
    import uvicorn
    from jatayu.logging import setup_logging
    setup_logging()
    logger.info("Jatayu OS starting — http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")




if __name__ == "__main__":
    main()

