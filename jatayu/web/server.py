"""Jatayu OS — Web server with WebSocket chat and REST API.

Wraps the existing Brain, tools, and memory into a web interface.
Run with: python -m jatayu.web.server
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path

# ── Performance debug flag ──
# Set JATAYU_PERF_DEBUG=1 in environment to log per-stage timing on every request.
_PERF_DEBUG: bool = os.getenv("JATAYU_PERF_DEBUG", "0").strip() == "1"


def _perf_log(label: str, t0: float, app_state=None) -> float:
    """Log elapsed time since t0 and return current time. No-op unless _PERF_DEBUG."""
    if app_state is not None:
        setattr(app_state, "current_stage", label)
    if _PERF_DEBUG:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        import logging
        logging.getLogger("jatayu.perf").info("[PERF] %-35s %6.1f ms", label, elapsed_ms)
    return time.perf_counter()

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from jatayu.brain import Brain
from jatayu.config import get_config, reset_config
from jatayu.core.organization import get_current_org
from jatayu.voice.voice_manager import VoiceManager
from jatayu.voice.speech_formatter import format_for_speech
from jatayu.conversation.service import ConversationService
from jatayu.core.backup import create_backup_archive
from jatayu.memory.entities import list_entities
from jatayu.memory.graph.store import RelationshipGraph

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

# Mount WhatsApp webhook (Communication Layer)
from jatayu.comms.whatsapp.webhook import router as wa_router
app.include_router(wa_router)


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
    """Build and wire all pipeline services.

    Returns a dict of services so _init_communication_layer can inject them
    into the Dispatcher. If any service fails, its key maps to None and
    the Dispatcher falls back gracefully.
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
        from jatayu.pipeline.brain_state import BrainStateService
        services["brain_state"] = BrainStateService(
            data_dir, event_log=services.get("event_log")
        )
        _log.info("Pipeline: BrainStateService ready")
    except Exception as exc:
        _log.error("Pipeline: BrainStateService failed: %s", exc)
        services["brain_state"] = None

    try:
        from jatayu.pipeline.intent_classifier import IntentClassifier
        services["intent_classifier"] = IntentClassifier()
        _log.info("Pipeline: IntentClassifier ready")
    except Exception as exc:
        _log.error("Pipeline: IntentClassifier failed: %s", exc)
        services["intent_classifier"] = None

    try:
        from jatayu.pipeline.task_extractor import TaskExtractor
        # entities.py exposes module-level functions; wrap in an adapter for uniform injection
        try:
            from jatayu.memory import entities as _ent_mod

            class _EntityMemoryAdapter:
                """Thin adapter wrapping entities.py module-level functions."""
                def get_person(self, name: str):
                    return _ent_mod.get_person(name)
                def get_project(self, name: str):
                    return _ent_mod.get_project(name)
                def list_entities(self, entity_type: str | None = None, include_deleted: bool = False):
                    return _ent_mod.list_entities(entity_type, include_deleted)

            entity_mem = _EntityMemoryAdapter()
        except Exception:
            entity_mem = None
        services["task_extractor"] = TaskExtractor(entity_memory=entity_mem)
        services["entity_memory"] = entity_mem
        _log.info("Pipeline: TaskExtractor ready")
    except Exception as exc:
        _log.error("Pipeline: TaskExtractor failed: %s", exc)
        services["task_extractor"] = None
        services["entity_memory"] = None


    try:
        from jatayu.pipeline.context_builder import ContextBuilder
        from jatayu.memory.retriever import ContextRetriever
        
        # ── Graph Memory Layer (Phase 4) ──
        try:
            from jatayu.memory.graph import RelationshipGraph, MemoryConfidenceService, GraphContextRetriever
            services["memory_graph"] = RelationshipGraph(data_dir=data_dir)
            services["memory_confidence"] = MemoryConfidenceService(data_dir=data_dir)
            services["graph_retriever"] = GraphContextRetriever(
                graph=services["memory_graph"],
                entity_store=services.get("entity_memory") # Uses adapter
            )
            _log.info("Pipeline: Graph Memory Layer ready")
        except Exception as exc:
            _log.error("Pipeline: Graph Memory Layer failed: %s", exc)
            services["memory_graph"] = None
            services["memory_confidence"] = None
            services["graph_retriever"] = None
            
        services["context_builder"] = ContextBuilder(
            base_system_prompt=brain_instance._base_system_prompt,
            entity_memory=services.get("entity_memory"),
            flat_memory=ContextRetriever(),
            tool_registry=brain_instance.registry,
            conv_service=conv_service,
            graph_retriever=services.get("graph_retriever"),
        )
        _log.info("Pipeline: ContextBuilder ready")
    except Exception as exc:
        _log.error("Pipeline: ContextBuilder failed: %s", exc)
        services["context_builder"] = None

    try:
        from jatayu.pipeline.planner import Planner
        services["planner"] = Planner()
        _log.info("Pipeline: Planner ready")
    except Exception as exc:
        _log.error("Pipeline: Planner failed: %s", exc)
        services["planner"] = None

    try:
        from jatayu.pipeline.intent_router import IntentRouter
        services["intent_router"] = IntentRouter(
            agent_registry=brain_instance.agents,
            brain_state=services.get("brain_state"),
        )
        _log.info("Pipeline: IntentRouter ready")
    except Exception as exc:
        _log.error("Pipeline: IntentRouter failed: %s", exc)
        services["intent_router"] = None

    try:
        from jatayu.pipeline.model_router import ModelRouter
        services["model_router"] = ModelRouter(
            brain_state=services.get("brain_state")
        )
        _log.info("Pipeline: ModelRouter ready")
    except Exception as exc:
        _log.error("Pipeline: ModelRouter failed: %s", exc)
        services["model_router"] = None

    try:
        from jatayu.pipeline.response_builder import ResponseBuilder
        services["response_builder"] = ResponseBuilder(
            entity_memory=services.get("entity_memory")
        )
        _log.info("Pipeline: ResponseBuilder ready")
    except Exception as exc:
        _log.error("Pipeline: ResponseBuilder failed: %s", exc)
        services["response_builder"] = None

    # ── Install confirmation gate callback (per-action CLI or fail-closed default) ──
    try:
        from jatayu.safety.gates import install_ws_confirmation_callback
        cli_confirm = os.getenv("JATAYU_CLI_CONFIRM", "0").strip() == "1"
        demo_mode = get_config().get("demo_mode", False)

        if cli_confirm:
            if demo_mode:
                raise ValueError("CRITICAL SECURITY ERROR: JATAYU_CLI_CONFIRM cannot be enabled when demo_mode is True!")
            _log.warning("=" * 80)
            _log.warning("⚠️ WARNING: PER-ACTION CLI INTERACTIVE CONFIRMATION MODE IS ACTIVE")
            _log.warning("Destructive actions will prompt for explicit (y/n) console confirmation per-call.")
            _log.warning("=" * 80)

            def per_action_cli_gate(tool, args, desc):
                print("\n" + "=" * 60)
                print(f"🔒 PER-ACTION CONFIRMATION REQUIRED FOR: {tool}")
                if desc:
                    print(f"   What: {desc}")
                print(f"   Args: {args}")
                print("=" * 60)
                try:
                    ans = input(f"Proceed with action '{tool}'? (y/n): ").strip().lower()
                    approved = ans in ("y", "yes")
                    print(f"   → Action '{tool}': {'APPROVED' if approved else 'DENIED'}\n")
                    return approved
                except (KeyboardInterrupt, EOFError, ValueError) as exc:
                    print(f"   → Action '{tool}': DENIED (stdin detached/cancelled: {exc})\n")
                    return False

            install_ws_confirmation_callback(per_action_cli_gate)
            _log.info("Pipeline: Per-action CLI confirmation gate installed")
        else:
            # Default production mode: fail-closed False (auto-deny until Phase 6 WS approval modal)
            install_ws_confirmation_callback(lambda tool, args, desc: False)
            _log.info("Pipeline: Default fail-closed confirmation gate installed (auto-deny until Phase 6 WS approval modal)")

    except Exception as exc:
        _log.error("Pipeline: Confirmation gate callback failed: %s", exc)
        raise

    # ── Workspace Intelligence Layer ─────────────────────────────────
    try:
        from jatayu.workspace.service import WorkspaceService
        services["workspace_service"] = WorkspaceService(
            data_dir=data_dir,
            event_log=services.get("event_log"),
        )
        _log.info("Pipeline: WorkspaceService ready")
    except Exception as exc:
        _log.error("Pipeline: WorkspaceService failed: %s", exc)
        services["workspace_service"] = None

    try:
        from jatayu.workspace.fast_capture import FastCapture
        services["fast_capture"] = FastCapture(
            workspace_service=services.get("workspace_service")
        )
        _log.info("Pipeline: FastCapture ready")
    except Exception as exc:
        _log.error("Pipeline: FastCapture failed: %s", exc)
        services["fast_capture"] = None

    try:
        from jatayu.workspace.timeline import TimelineRecorder
        recorder = TimelineRecorder(
            workspace_service=services["workspace_service"],
            event_log=services.get("event_log"),
        ) if services.get("workspace_service") else None
        if recorder:
            recorder.start()
        services["timeline_recorder"] = recorder
        _log.info("Pipeline: TimelineRecorder ready")
    except Exception as exc:
        _log.error("Pipeline: TimelineRecorder failed: %s", exc)
        services["timeline_recorder"] = None

    try:
        from jatayu.intelligence.proactive import ProactiveIntelligenceEngine
        services["proactive_engine"] = ProactiveIntelligenceEngine(
            workspace_service=services["workspace_service"],
            event_log=services.get("event_log")
        ) if services.get("workspace_service") else None
        _log.info("Pipeline: ProactiveIntelligenceEngine ready")
    except Exception as exc:
        _log.error("Pipeline: ProactiveIntelligenceEngine failed: %s", exc)
        services["proactive_engine"] = None

    try:
        from jatayu.pipeline.propagation import KnowledgePropagationService
        services["knowledge_propagation"] = KnowledgePropagationService(
            event_log=services.get("event_log"),
            workspace_service=services.get("workspace_service"),
            entity_memory=services.get("entity_memory")
        ) if services.get("event_log") else None
        _log.info("Pipeline: KnowledgePropagationService ready")
    except Exception as exc:
        _log.error("Pipeline: KnowledgePropagationService failed: %s", exc)
        services["knowledge_propagation"] = None

    try:
        from jatayu.workspace.daily_brief import DailyBriefAggregator
        services["daily_brief"] = DailyBriefAggregator(
            workspace_service=services["workspace_service"],
            proactive_engine=services.get("proactive_engine")
        ) if services.get("workspace_service") else None
        _log.info("Pipeline: DailyBriefAggregator ready")
    except Exception as exc:
        _log.error("Pipeline: DailyBriefAggregator failed: %s", exc)
        services["daily_brief"] = None

    try:
        from jatayu.workspace.suggestions import SuggestionEngine
        services["suggestion_engine"] = SuggestionEngine(
            workspace_service=services["workspace_service"]
        ) if services.get("workspace_service") else None
        _log.info("Pipeline: SuggestionEngine ready")
    except Exception as exc:
        _log.error("Pipeline: SuggestionEngine failed: %s", exc)
        services["suggestion_engine"] = None

    try:
        from jatayu.intelligence.chief import ChiefOfStaffService
        services["chief_of_staff"] = ChiefOfStaffService(brain_instance, services)
        _log.info("Pipeline: ChiefOfStaffService ready")
    except Exception as exc:
        _log.error("Pipeline: ChiefOfStaffService failed: %s", exc)
        services["chief_of_staff"] = None

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
    """Initialize the Communication Layer and all configured providers.

    Core objects (Dispatcher, Registry, SessionManager, Router) are built
    once. Each provider is then independently registered if its credentials
    are present. Providers that are not configured are silently skipped.

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
        brain_state=p.get("brain_state"),
        intent_classifier=p.get("intent_classifier"),
        task_extractor=p.get("task_extractor"),
        context_builder=p.get("context_builder"),
        planner=p.get("planner"),
        intent_router=p.get("intent_router"),
        model_router=p.get("model_router"),
        response_builder=p.get("response_builder"),
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

            print(f"📨  Telegram provider registered")
            if tg_users:
                print(f"    Authorized user IDs: {tg_users}")
            else:
                print("    ℹ️  No TELEGRAM_AUTHORIZED_USERS set — logging all user IDs on first message")

        except Exception as e:
            print(f"⚠️  Telegram init failed: {e}")
            import traceback; traceback.print_exc()
    else:
        print("📨  Telegram not configured (no TELEGRAM_BOT_TOKEN)")

    # ── WhatsApp (Paused — credentials preserved, not active) ──
    wa_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if wa_token and wa_phone_id:
        try:
            from jatayu.comms.whatsapp.adapter import WhatsAppAdapter
            from jatayu.comms.whatsapp.webhook import set_comm_router

            wa_adapter = WhatsAppAdapter(access_token=wa_token, phone_number_id=wa_phone_id)
            provider_registry.register(wa_adapter)
            print(f"📱  WhatsApp provider registered (paused — no active SIM)")
        except Exception as e:
            print(f"⚠️  WhatsApp init failed: {e}")

    # ── Build the Communication Router ──
    if len(provider_registry) == 0:
        print("ℹ️  No messaging providers configured — Communication Layer idle")
        return

    comm_router = CommunicationRouter(
        dispatcher=dispatcher,
        registry=provider_registry,
        session_manager=session_mgr,
        voice_manager=voice_mgr,
        authorized_users=authorized_users,
    )

    # Inject router into WhatsApp webhook handler
    try:
        from jatayu.comms.whatsapp.webhook import set_comm_router
        set_comm_router(comm_router)
    except Exception:
        pass

    # ── Start Telegram long polling as an asyncio background task ──
    if tg_token and "telegram" in provider_registry:
        tg_users = authorized_users.get("telegram", [])
        tg_polling_task = asyncio.create_task(
            start_telegram_polling(tg_token, comm_router, authorized_users=tg_users or None)
        )
        app.state.tg_polling_task = tg_polling_task
        print("📨  Telegram long polling task started")

    print(f"✅  Communication Layer active — providers: {provider_registry.list_providers()}")



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


# ── REST API for Workspace Intelligence Layer ──

@app.get("/api/workspaces")
async def list_workspaces():
    """List all workspaces with summary and health."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"workspaces": [], "error": "WorkspaceService not available"}
    from jatayu.workspace.health import WorkspaceHealthCalculator
    calc = WorkspaceHealthCalculator()
    workspaces = svc.list_all()
    return {
        "workspaces": [
            {**ws.to_summary(), "health": calc.compute(ws).to_dict()}
            for ws in workspaces
        ]
    }


@app.post("/api/workspaces")
async def create_workspace(request: Request):
    """Create a workspace for a project entity."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"error": "WorkspaceService not available"}
    body = await request.json()
    entity_id = body.get("entity_id")
    name = body.get("name")
    if not entity_id or not name:
        return {"error": "entity_id and name are required"}
    ws = svc.get_or_create(entity_id, name)
    return {"workspace": ws.to_summary(), "created": True}


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Return full workspace detail."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"error": "WorkspaceService not available"}
    ws = svc.get_by_id(workspace_id)
    if not ws:
        return {"error": "Workspace not found"}
    from jatayu.workspace.health import WorkspaceHealthCalculator
    health = WorkspaceHealthCalculator().compute(ws)
    return {
        "workspace": ws.to_dict(),
        "health": health.to_dict(),
        "task_count": len(ws.tasks),
        "note_count": len(ws.notes),
        "meeting_count": len(ws.meetings),
    }


@app.get("/api/workspaces/{workspace_id}/timeline")
async def get_workspace_timeline(workspace_id: str, limit: int = 50):
    """Return the workspace activity timeline."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"timeline": [], "error": "WorkspaceService not available"}
    timeline = svc.get_timeline(workspace_id, limit=limit)
    return {"workspace_id": workspace_id, "timeline": [e.to_dict() for e in timeline]}


@app.get("/api/workspaces/{workspace_id}/health")
async def get_workspace_health(workspace_id: str):
    """Return workspace health score and breakdown."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"error": "WorkspaceService not available"}
    health = svc.compute_health(workspace_id)
    return {"health": health.to_dict()}


@app.post("/api/workspaces/{workspace_id}/tasks")
async def add_workspace_task(workspace_id: str, request: Request):
    """Add a task to a workspace."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"error": "WorkspaceService not available"}
    body = await request.json()
    from jatayu.workspace.models import WorkspaceTask
    task = WorkspaceTask.new(
        title=body.get("title", ""),
        description=body.get("description", ""),
        priority=int(body.get("priority", 3)),
        due_date=body.get("due_date"),
        assigned_to=body.get("assigned_to"),
        depends_on=body.get("depends_on", []),
        tags=body.get("tags", []),
        entity_refs=body.get("entity_refs", []),
        workspace_id=workspace_id,
        source="api",
    )
    saved = svc.add_task(workspace_id, task)
    if not saved:
        return {"error": "Workspace not found"}
    return {"task": saved.to_dict()}


@app.patch("/api/workspaces/{workspace_id}/tasks/{task_id}")
async def update_task_status(workspace_id: str, task_id: str, request: Request):
    """Update a task's status (todo/in_progress/done/blocked/cancelled)."""
    svc = getattr(app.state, "pipeline", {}).get("workspace_service")
    if not svc:
        return {"error": "WorkspaceService not available"}
    body = await request.json()
    new_status = body.get("status")
    if not new_status:
        return {"error": "status is required"}
    updated = svc.update_task_status(workspace_id, task_id, new_status)
    if not updated:
        return {"error": "Task or workspace not found"}
    return {"task": updated.to_dict()}


@app.post("/api/capture")
async def fast_capture(request: Request):
    """Classify a message and attach items to a workspace.

    Body: { text: str, session_id?: str, active_project_entity_id?: str }
    """
    fc = getattr(app.state, "pipeline", {}).get("fast_capture")
    if not fc:
        return {"error": "FastCapture not available"}
    body = await request.json()
    text = body.get("text", "")
    if not text.strip():
        return {"error": "text is required"}

    # Build session context from request body
    session_context = {}
    if body.get("active_project_entity_id"):
        session_context["active_project_entity_id"] = body["active_project_entity_id"]

    result = fc.capture(text, session_context=session_context)
    return result.to_dict()


@app.get("/api/daily-brief")
async def get_daily_brief():
    """Return the structured Morning Brief."""
    aggregator = getattr(app.state, "pipeline", {}).get("daily_brief")
    if not aggregator:
        return {"error": "DailyBriefAggregator not available"}
    brief = aggregator.generate()
    return brief.to_dict()


@app.get("/api/daily-context")
async def get_daily_context():
    """Return situational daily context (Weather & environment)."""
    svc = getattr(app.state, "pipeline", {}).get("daily_context")
    if not svc:
        from jatayu.context import DailyContextService
        svc = DailyContextService()
    return svc.get_daily_context()


@app.get("/api/suggestions")
async def get_suggestions(workspace_id: str | None = None):
    """Return proactive suggestions, optionally scoped to a workspace."""
    engine = getattr(app.state, "pipeline", {}).get("suggestion_engine")
    if not engine:
        return {"suggestions": [], "error": "SuggestionEngine not available"}
    suggestions = engine.generate(workspace_id=workspace_id)
    return {"suggestions": [s.to_dict() for s in suggestions]}



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
    """Aggregated system health endpoint."""
    pipeline = getattr(app.state, "pipeline", None)
    graph = RelationshipGraph()
    entities = list_entities()
    
    ws_count = 0
    ws_service = pipeline.get("workspace_service") if pipeline else None
    if ws_service:
        ws_count = len(ws_service.list_all(include_deleted=False))
        
    prop_service = pipeline.get("propagation_service") if pipeline else None
    prop_runs = len(prop_service._runs) if prop_service else 0
    
    from jatayu.tools.obsidian import _is_running as obsidian_running
    
    return {
        "status": "online",
        "version": "1.5.0 (v5 Final)",
        "brain_status": "optimal" if brain else "offline",
        "workspace_status": f"{ws_count} active workspaces",
        "memory_status": f"{len(entities)} known entities",
        "graph_status": f"{len(graph._edges)} active edges",
        "propagation_queue": f"{prop_runs} total runs tracked",
        "obsidian_sync_status": "connected" if obsidian_running() else "offline",
    }


@app.get("/api/search")
async def global_search(q: str = ""):
    """Unified search endpoint across entities, workspaces, memory, and graph."""
    if not q:
        return {"results": []}
        
    query = q.lower()
    results = []
    
    # 1. Entities
    for e in list_entities():
        name = e.get("name", "").lower()
        aliases = [a.lower() for a in e.get("aliases", [])]
        if query in name or any(query in a for a in aliases):
            results.append({"type": "entity", "id": e.get("id"), "name": e.get("name"), "entity_type": e.get("type")})
            
    # 2. Workspaces & Tasks
    pipeline = getattr(app.state, "pipeline", None)
    if pipeline and "workspace_service" in pipeline:
        for ws in pipeline["workspace_service"].list_all():
            if query in ws.name.lower():
                results.append({"type": "workspace", "id": ws.id, "name": ws.name})
            for t in ws.get_tasks():
                if query in t.title.lower() or query in t.description.lower():
                    results.append({"type": "task", "id": t.id, "title": t.title, "workspace_id": ws.id})
                    
    # 3. Flat Memory
    memories = _load_json("memory.json")
    for m in memories:
        if query in m.get("content", "").lower():
            results.append({"type": "memory", "id": m.get("id"), "content": m.get("content")})
            
    return {"results": results}


@app.get("/api/export")
async def export_data():
    """Export JATAYU state as a ZIP archive."""
    try:
        archive_path = create_backup_archive()
        return FileResponse(
            path=archive_path, 
            filename=Path(archive_path).name, 
            media_type="application/zip"
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}




@app.get("/api/agents")
async def get_agents():
    """Return all registered agents and their statuses."""
    if not brain:
        return {}
    return brain.agents.to_dict()


@app.get("/api/agents/{name}/health")
async def check_agent_health(name: str):
    """Check health of a specific agent."""
    if not brain:
        return {"status": "error"}
    agent = brain.agents.get(name)
    if not agent:
        return {"status": "error", "message": f"Agent {name} not found"}
    is_healthy = brain.agents.check_health(name)
    return {"name": name, "status": agent.status, "healthy": is_healthy}


@app.get("/api/capabilities")
async def get_capabilities():
    """Return all registered capabilities and their tool mappings."""
    if not brain:
        return {}
    return brain.capabilities.to_dict()


@app.get("/api/organization")
async def get_organization():
    """Return current organization info."""
    return get_current_org().to_dict()


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
        return {"status": "error", "summary": "Brain not initialized"}
    
    body = await request.json()
    action = body.get("action")
    kwargs = body.get("kwargs", {})
    
    if not action:
        return {"status": "error", "summary": "Action is required"}
        
    plugin = brain.plugin_manager.plugins.get(plugin_id)
    if not plugin:
        return {"status": "error", "summary": f"Plugin {plugin_id} not found"}
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
        loop = asyncio.get_event_loop()
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                error_body = resp.text[:300]
                print(f"\n⚠️  ElevenLabs TTS HTTP {resp.status_code}: {error_body}")
                return Response(
                    content=b"",
                    media_type="audio/mpeg",
                    headers={"X-TTS-Error": f"ElevenLabs HTTP {resp.status_code}"},
                )
            return Response(content=resp.content, media_type="audio/mpeg")

    except Exception as e:
        print(f"\n⚠️  TTS error: {e}")
        return Response(
            content=b"",
            media_type="audio/mpeg",
            headers={"X-TTS-Error": str(e)[:200]},
        )


# ── Chief of Staff Endpoints ──

@app.get("/api/chief/state")
async def get_chief_state(date: str):
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    return chief.get_state(date)

@app.post("/api/chief/morning-brief")
async def post_morning_brief(body: dict):
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    date_str = body.get("date")
    if not date_str:
        return {"error": "date is required"}
    return chief.generate_morning_brief(date_str)

@app.post("/api/chief/afternoon-checkin")
async def post_afternoon_checkin(body: dict):
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    date_str = body.get("date")
    if not date_str:
        return {"error": "date is required"}
    return chief.generate_afternoon_checkin(date_str)

@app.post("/api/chief/night-debrief")
async def post_night_debrief(body: dict):
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    date_str = body.get("date")
    answers = body.get("answers", {})
    if not date_str:
        return {"error": "date is required"}
    return chief.generate_night_debrief(date_str, answers)

@app.post("/api/chief/habit/toggle")
async def post_habit_toggle(body: dict):
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    date_str = body.get("date")
    habit_name = body.get("habit")
    if not date_str or not habit_name:
        return {"error": "date and habit are required"}
    return chief.toggle_habit(date_str, habit_name)

@app.get("/api/chief/system-health")
async def get_chief_system_health():
    chief = getattr(app.state, "pipeline", {}).get("chief_of_staff")
    if not chief:
        return {"error": "ChiefOfStaffService not available"}
    return chief.get_system_health()


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
            loop = asyncio.get_event_loop()
            chunks_queue: asyncio.Queue = asyncio.Queue()

            def ws_confirmation_gate(tool_name, args, desc):
                import threading
                req_id = str(uuid.uuid4())
                evt = threading.Event()
                state = {"event": evt, "approved": False}
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

                _t = _perf_log("Stage 1: Intent classification", _t_start)

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

                    # Resolve /brief sentinel
                    if reply_text == "__SLASH_BRIEF__":
                        try:
                            daily_brief_svc = getattr(app.state, "pipeline", {}).get("daily_brief")
                            if daily_brief_svc:
                                reply_text = await loop.run_in_executor(
                                    None, daily_brief_svc.get_brief
                                )
                            else:
                                reply_text = "Daily brief service not available yet."
                        except Exception:
                            reply_text = "Could not generate daily brief."

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

                _t = _perf_log("Stage 1b: Command center check", _t_start)

                # ── STAGE 2: Knowledge Pre-fetch (conditional + async) ───────────
                # Phase 6: circuit breaker guards AnythingLLM
                retrieved_context = ""
                if needs_knowledge:
                    breaker = getattr(app.state, "anythingllm_breaker", None)
                    if breaker and breaker.is_open():
                        pass  # circuit open — skip to vault fallback
                    else:
                        try:
                            plugin = brain.plugin_manager.plugins.get("anythingllm")
                            if plugin:
                                def _do_knowledge_fetch():
                                    res = plugin.execute("knowledge_search", query=user_text)
                                    if res and res.status == "success":
                                        txt = res.data.get("response", "")
                                        if "Found in Vault" in txt or "[Semantic]" in txt or "Sources:" in txt:
                                            return txt
                                    elif res and res.status == "error":
                                        raise RuntimeError(f"AnythingLLM error: {res.error}")
                                    return ""
                                retrieved_context = await loop.run_in_executor(
                                    None, _do_knowledge_fetch
                                )
                                if breaker:
                                    breaker.record_success()
                        except Exception:
                            if breaker:
                                breaker.record_failure()

                _t = _perf_log("Stage 2: Knowledge pre-fetch", _t_start)

                # ── STAGE 3: Prompt + Context Assembly ───────────────────────────
                enhanced_prompt = user_text
                system_prompt_override = None

                # Phase 5: ContextBuilder for relevance-filtered system prompt
                context_builder = getattr(app.state, "pipeline", {}).get("context_builder")
                if context_builder and intent_result:
                    try:
                        from jatayu.pipeline.task_extractor import TaskExtractor
                        task_extractor = getattr(app.state, "pipeline", {}).get("task_extractor")
                        if task_extractor:
                            task = task_extractor.extract(user_text)
                        else:
                            from jatayu.pipeline.task_extractor import Task
                            task = Task(goal=user_text, entities=[])

                        brain_state_svc = getattr(app.state, "pipeline", {}).get("brain_state")
                        snapshot = brain_state_svc.snapshot() if brain_state_svc else None

                        if snapshot:
                            packet = context_builder.build(
                                intent=intent_result,
                                task=task,
                                snapshot=snapshot,
                                conversation_id=conv_id,
                            )
                            system_prompt_override = packet.system_prompt
                            tools_to_expose = packet.tools_to_expose

                            # Phase 5: Recipient pre-resolution for email/calendar/telegram
                            _contact_intents = {"email", "calendar", "meeting", "telegram_send"}
                            if intent_result.intent in _contact_intents and packet.relevant_entities:
                                contact_lines = []
                                for ent in packet.relevant_entities[:5]:
                                    name = ent.get("name", "")
                                    email = ent.get("email", "")
                                    if name and email:
                                        contact_lines.append(f"- {name}: {email}")
                                if contact_lines:
                                    system_prompt_override += (
                                        "\n\nCONTEXT CONTACTS (pre-resolved — do NOT call get_person for these):\n"
                                        + "\n".join(contact_lines)
                                    )
                    except Exception as _cbe:
                        import logging as _log
                        _log.getLogger("jatayu.server").debug(
                            "ContextBuilder skipped: %s", _cbe
                        )

                if retrieved_context:
                    enhanced_prompt = (
                        f"User asked: {user_text}\n\n"
                        f"Internal Knowledge Context:\n{retrieved_context}\n\n"
                        "Please answer the user's question using this internal knowledge."
                    )

                _t = _perf_log("Stage 3: Prompt construction", _t_start)

                # ── STAGE 4: Model Routing (Phase 4) ────────────────────────────
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

                _t = _perf_log("Stage 3b: Model routing", _t_start)

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
                        system_prompt_override=system_prompt_override,
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

                _t = _perf_log("Stage 5: Brain + LLM call", _t_start)

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
                    except Exception:
                        pass

                # ── STAGE 5b: Fallback / Done ────────────────────────────────────
                memory_context = ""

                if "Couldn't reach the model" in combined_text:
                    # DEPRECATED: _offline_router is only reached when Gemini is unreachable.
                    # Phase 2 Qwen-local will replace this for offline conversation.
                    fallback_reply = await _offline_router(
                        user_text, retrieved_context, memory_context, brain, loop, ws
                    )
                    await ws.send_json({"type": "done", "text": fallback_reply, "conversation_id": conv_id})
                    if history and conv_id:
                        history.append_message(conv_id, role="assistant", content=fallback_reply, status="complete", provider="dashboard")
                else:
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

                _t = _perf_log("Stage 6: Response delivery", _t_start)

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

                _perf_log("Stage 7: Panel refresh", _t_start)

            demo_mode = get_config().get("demo_mode", False)
            watchdog_limit = 12.0 if demo_mode else 25.0
            try:
                await asyncio.wait_for(run_brain(), timeout=watchdog_limit)
            except asyncio.TimeoutError:
                # Mark session as cancelled so background thread aborts tool execution
                session_obj = brain._sessions.get(session_id)
                if session_obj:
                    session_obj.is_cancelled = True

                last_stage = getattr(app.state, "current_stage", "unknown")
                import logging as _log
                _log.getLogger("jatayu.server").error(
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


async def _offline_router(user_text, retrieved_context, memory_context, brain, loop, ws):
    """Smart, cost-aware intent router for when Gemini is unavailable.
    
    Priority: FREE tools first, Hermes (paid Google API) only for complex tasks.
    
    Routes:
    - Simple file ops (create/delete folder) → Python subprocess (FREE)
    - Browser/web tasks → Python webbrowser module (FREE)
    - Obsidian tasks → Obsidian REST API (FREE)
    - Knowledge questions → Qwen + Vault (FREE)
    - Complex coding/engineering → Hermes CLI (PAID - last resort)
    """
    text_lower = user_text.lower()
    
    # ── INTENT CLASSIFICATION ──
    
    # 1. Simple file operations (FREE via subprocess)
    simple_file_keywords = [
        "create a folder", "create folder", "make a folder", "make folder",
        "delete folder", "delete file", "remove folder", "remove file",
        "rename file", "rename folder", "move file", "copy file",
    ]
    
    # 2. Explicit Hermes request (PAID)
    hermes_keywords = ["hermes", "hey hermes"]
    
    # 3. Browser/web tasks (FREE via webbrowser)
    browser_keywords = [
        "browser", "browse", "search the web", "open website", "open url",
        "go to", "navigate to", "search for", "look up online",
        "browser-use", "browser use", "open this", "visit", "open the website",
    ]
    
    # 4. Obsidian tasks (FREE via REST API)
    obsidian_keywords = [
        "obsidian", "vault", "note", "daily note", "write a note", "read note",
        "save to obsidian", "search vault", "list notes",
    ]
    
    # 5. OpenClaw (FREE if running)
    openclaw_keywords = ["openclaw", "open claw", "claw"]
    
    # Classify intent
    route = "qwen"  # default (FREE)
    for kw in hermes_keywords:
        if kw in text_lower:
            route = "hermes"
            break
    if route == "qwen":
        for kw in simple_file_keywords:
            if kw in text_lower:
                route = "local_file"
                break
    if route == "qwen":
        for kw in browser_keywords:
            if kw in text_lower:
                route = "browser"
                break
    if route == "qwen":
        for kw in obsidian_keywords:
            if kw in text_lower:
                route = "obsidian"
                break
    if route == "qwen":
        for kw in openclaw_keywords:
            if kw in text_lower:
                route = "openclaw"
                break
    
    # ── ROUTE: LOCAL FILE OPS (FREE) ──
    if route == "local_file":
        await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Handling file operation locally (free)...*\n\n"})
        try:
            def do_file_op():
                import subprocess, re, os
                # Extract folder/file name from common patterns
                # "create a folder named X on my desktop"
                # "delete the folder X from desktop"
                name_match = re.search(r'(?:named?|called)\s+["\']?(.+?)["\']?\s*(?:on|in|from|at|$)', user_text, re.IGNORECASE)
                if not name_match:
                    name_match = re.search(r'(?:folder|file)\s+["\']?(.+?)["\']?\s*(?:on|in|from|at|$)', user_text, re.IGNORECASE)
                
                name = name_match.group(1).strip().rstrip('!.') if name_match else None
                
                # Determine location
                location = os.path.expanduser("~/Desktop")
                if "download" in text_lower:
                    location = os.path.expanduser("~/Downloads")
                elif "document" in text_lower:
                    location = os.path.expanduser("~/Documents")
                
                if "create" in text_lower or "make" in text_lower:
                    if name:
                        path = os.path.join(location, name)
                        os.makedirs(path, exist_ok=True)
                        return f"✅ Created folder: `{path}`"
                    return "⚠️ Could not determine folder name. Try: 'Create a folder named X on my desktop'"
                
                elif "delete" in text_lower or "remove" in text_lower:
                    if name:
                        import shutil
                        path = os.path.join(location, name)
                        if os.path.exists(path):
                            if os.path.isdir(path):
                                shutil.rmtree(path)
                            else:
                                os.remove(path)
                            return f"✅ Deleted: `{path}`"
                        return f"⚠️ Not found: `{path}`"
                    return "⚠️ Could not determine what to delete."
                
                return "⚠️ Could not understand the file operation. Try being more specific."
            
            result = await loop.run_in_executor(None, do_file_op)
            return f"📁 **Local File Manager (Free):**\n\n{result}"
        except Exception as e:
            return f"⚠️ File operation error: {e}"
    
    # ── ROUTE: BROWSER (FREE) ──
    if route == "browser":
        await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Opening browser (free)...*\n\n"})
        try:
            def do_browser():
                import webbrowser, re, urllib.parse
                
                # Extract URL or search query
                url_match = re.search(r'(https?://\S+)', user_text)
                if url_match:
                    url = url_match.group(1)
                    webbrowser.open(url)
                    return f"✅ Opened: {url}"
                
                # Search patterns
                search_match = re.search(r'(?:search\s+(?:for\s+)?|look\s+up\s+|find\s+|open\s+)(?:the\s+)?(?:website\s+|site\s+|repo\s+|github\s+repo\s+)?["\']?(.+?)["\']?\s*(?:on|in|$)', user_text, re.IGNORECASE)
                if not search_match:
                    search_match = re.search(r'(?:search|find|open|visit|go to|navigate to)\s+(.+?)$', user_text, re.IGNORECASE)
                
                if search_match:
                    query = search_match.group(1).strip().rstrip('!.')
                    # Check for GitHub
                    if "github" in text_lower:
                        url = f"https://github.com/search?q={urllib.parse.quote(query)}"
                    else:
                        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    webbrowser.open(url)
                    return f"✅ Opened browser search for: '{query}'\n🔗 {url}"
                
                return "⚠️ Could not determine what to search/open. Try: 'Search for X' or 'Open website https://...'"
            
            result = await loop.run_in_executor(None, do_browser)
            return f"🌐 **Browser (Free):**\n\n{result}"
        except Exception as e:
            return f"⚠️ Browser error: {e}"
    
    # ── ROUTE: OBSIDIAN (FREE) ──
    if route == "obsidian":
        await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Connecting to Obsidian (free)...*\n\n"})
        try:
            def do_obsidian():
                from jatayu.tools.obsidian import obsidian_search, obsidian_list_files, obsidian_read_note, obsidian_write_note
                
                if "create" in text_lower or "write" in text_lower or "make" in text_lower or "add" in text_lower:
                    import re
                    name_match = re.search(r'(?:named?|called)\s+["\']?(.+?)["\']?\s*(?:in|$)', user_text, re.IGNORECASE)
                    if not name_match:
                        name_match = re.search(r'(?:note|folder|file|directory)\s+["\']?(.+?)["\']?\s*(?:in|$)', user_text, re.IGNORECASE)
                    name = name_match.group(1).strip().rstrip('!.') if name_match else None
                    if not name:
                        return "⚠️ Could not determine note/folder name. Try: 'Create a note named X in Obsidian'"
                    
                    if "folder" in text_lower or "directory" in text_lower:
                        # Create dummy file to force folder creation
                        import httpx
                        import os
                        api_key = os.getenv("OBSIDIAN_API_KEY", "").strip()
                        try:
                            with httpx.Client(timeout=10, verify=False) as client:
                                resp = client.put(
                                    f"https://127.0.0.1:27124/vault/{name}/.keep.md",
                                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "text/markdown"},
                                    content="Folder created by Jatayu"
                                )
                                resp.raise_for_status()
                            return f"✅ Created folder in Obsidian: `{name}`"
                        except Exception as e:
                            return f"⚠️ Failed to create folder in Obsidian: {e}"
                    else:
                        return obsidian_write_note(name, f"# {name}\n\nCreated by Jatayu.")
                
                elif "list" in text_lower or "show" in text_lower:
                    return obsidian_list_files("/")
                elif "search" in text_lower:
                    import re
                    query_match = re.search(r'search\s+(?:for\s+)?(.+?)$', user_text, re.IGNORECASE)
                    query = query_match.group(1).strip() if query_match else user_text
                    return obsidian_search(query)
                elif "read" in text_lower:
                    import re
                    path_match = re.search(r'read\s+(?:note\s+)?(.+?)$', user_text, re.IGNORECASE)
                    path = path_match.group(1).strip() if path_match else ""
                    return obsidian_read_note(path)
                elif "daily" in text_lower:
                    from jatayu.tools.obsidian import obsidian_daily_note
                    return obsidian_daily_note()
                else:
                    return obsidian_list_files("/")
            
            result = await loop.run_in_executor(None, do_obsidian)
            return f"📝 **Obsidian (Free):**\n\n{result}"
        except Exception as e:
            return f"⚠️ Obsidian error: {e}"
    
    # ── ROUTE: OPENCLAW (FREE) ──
    if route == "openclaw":
        await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Routing to OpenClaw...*\n\n"})
        try:
            plugin = brain.plugin_manager.plugins.get("openclaw")
            if plugin:
                def run_openclaw():
                    return plugin.execute("delegate_action", action=user_text)
                res = await loop.run_in_executor(None, run_openclaw)
                if res.status == "success":
                    return f"🦾 **OpenClaw:**\n\n{res.data.get('reply', str(res.data))}"
                else:
                    return f"⚠️ OpenClaw is not currently running. Status: {res.summary}"
            else:
                return "⚠️ OpenClaw plugin not loaded."
        except Exception as e:
            return f"⚠️ OpenClaw error: {e}"
    
    # ── ROUTE: HERMES (PAID - only for explicit requests) ──
    if route == "hermes":
        await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Routing to Hermes (uses API credits)...*\n\n"})
        try:
            plugin = brain.plugin_manager.plugins.get("hermes")
            if plugin:
                def run_hermes():
                    return plugin.execute("delegate_coding", prompt=user_text)
                res = await loop.run_in_executor(None, run_hermes)
                if res.status == "success":
                    return f"🧠 **Hermes:**\n\n{res.data.get('reply', str(res.data))}"
                else:
                    return f"⚠️ Hermes failed: {res.summary}"
            else:
                return "⚠️ Hermes plugin not loaded."
        except Exception as e:
            return f"⚠️ Hermes error: {e}"
    
    # ── ROUTE: QWEN (FREE - default) ──
    await ws.send_json({"type": "chunk", "text": "\n\n🔄 *Switching to local Qwen brain (free)...*\n\n"})
    
    system_parts = [
        "You are JATAYU, the AI assistant for Artificial Budhi. Be concise and helpful.",
        "",
        "You have access to these plugins (tell the user to use them by name if needed):",
        "- 'Create a folder named X' → handled locally for free",
        "- 'Search for X' or 'Open website X' → opens browser for free",
        "- 'Search vault for X' → searches Obsidian for free",
        "- 'Hey Hermes, ...' → delegates to Hermes agent (uses API credits)",
        "- 'Hey OpenClaw, ...' → delegates to OpenClaw agent (for physical actions)",
        "",
        "If the user asks you to do something you cannot do, suggest which command they should use.",
    ]
    if memory_context:
        system_parts.append(f"\nUser Memory:\n{memory_context}")
    
    system_prompt = "\n".join(system_parts)
    
    local_prompt = user_text
    if retrieved_context:
        local_prompt = f"Answer the user's question using ONLY the following internal knowledge.\n\nInternal Knowledge:\n{retrieved_context}\n\nUser Question: {user_text}\n\nAnswer concisely based on the knowledge above:"
    
    from jatayu.pipeline.circuit_breaker import get_breaker
    breaker = get_breaker("qwen_local")
    if breaker.is_open():
        if retrieved_context:
            return f"⚠️ Local Qwen circuit open.\n\nRaw knowledge from your vault:\n\n{retrieved_context}"
        return "⚠️ Local Qwen circuit open and unavailable."

    try:
        def call_ollama():
            import requests
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen3-vl:4b-instruct",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": local_prompt}
                    ],
                    "stream": False
                },
                timeout=(2.0, 5.0)
            )
            resp.raise_for_status()
            breaker.record_success()
            return resp.json().get("message", {}).get("content", "No response from local model.")

        ollama_reply = await loop.run_in_executor(None, call_ollama)
        return f"🧠 **Local Brain (Qwen):**\n\n{ollama_reply}"
    except Exception as e:
        breaker.record_failure()
        if retrieved_context:
            return f"⚠️ Both Gemini and local Qwen are unavailable.\n\nHere is the raw knowledge from your vault:\n\n{retrieved_context}"
        else:
            return f"⚠️ Both Gemini and local Qwen are unavailable. Error: {e}"


# ── Entry point ──

def main():
    import uvicorn
    print("\n🪶  Jatayu OS — Divine Guardian Interface")
    print("   Starting web server on http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
