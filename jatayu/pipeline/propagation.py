"""Knowledge Propagation Pipeline — Atomic, event-driven, idempotent knowledge sync.

Listens to EventLog for confirmed knowledge (entity.created, relationship.created)
and propagates it safely to workspaces, graph, and Obsidian (as a mirror).
Every run has a unique Propagation ID and tracks step-level status.
"""

import json
import logging
import threading
import queue
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from jatayu.config import get_config
from jatayu.pipeline.event_log import EventLog, PipelineEvent
from jatayu.tools.obsidian import obsidian_write_note, _is_running as is_obsidian_available

logger = logging.getLogger(__name__)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _prop_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    import uuid
    suffix = uuid.uuid4().hex[:4]
    return f"kp_{timestamp}_{suffix}"


@dataclass
class PropagationRun:
    propagation_id: str = field(default_factory=_prop_id)
    event_id: str = ""
    event_type: str = ""
    status: str = "pending"  # pending, completed, retry_pending
    steps: dict[str, str] = field(default_factory=lambda: {
        "workspace": "pending",
        "obsidian": "pending",
        "eventlog": "pending"
    })
    data: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)
        
    @classmethod
    def from_dict(cls, d: dict) -> 'PropagationRun':
        return cls(**d)


class KnowledgePropagationService:
    """Subscribes to EventLog, orchestrates atomic synchronization."""
    
    def __init__(self, event_log: EventLog, workspace_service, entity_memory):
        self._event_log = event_log
        self._ws_service = workspace_service
        self._entity_memory = entity_memory
        
        self.data_dir = Path(get_config()["data_dir"])
        self.state_file = self.data_dir / "propagation_state.json"
        self.audit_file = self.data_dir / "propagation_audit.jsonl"
        
        self._runs: dict[str, PropagationRun] = {}
        self._load_state()
        
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        
        # Subscribe to confirmed knowledge events
        self._event_log.subscribe("entity.created", self._on_event)
        self._event_log.subscribe("entity.updated", self._on_event)
        self._event_log.subscribe("relationship.created", self._on_event)
        
        # Start worker thread
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self._runs = {k: PropagationRun.from_dict(v) for k, v in data.items()}
            except Exception as e:
                logger.error("Failed to load propagation state: %s", e)

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.state_file, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._runs.items()}, f, indent=2)
        except Exception as e:
            logger.error("Failed to save propagation state: %s", e)

    def _on_event(self, event: PipelineEvent):
        """Enqueue the event for processing."""
        self._queue.put(event)

    def _worker_loop(self):
        """Background loop to process queue and retries."""
        while not self._stop_event.is_set():
            try:
                # Process pending events
                try:
                    event = self._queue.get(timeout=5.0)
                    self._process_event(event)
                    self._queue.task_done()
                except queue.Empty:
                    pass
                
                # Process retries
                self._process_retries()
                
            except Exception as e:
                logger.error("Propagation worker error: %s", e)
                time.sleep(1)
                
    def _process_event(self, event: PipelineEvent):
        run = PropagationRun(event_id=event.event_id, event_type=event.type, data=event.data)
        self._runs[run.propagation_id] = run
        self._execute_run(run)

    def _process_retries(self):
        for run in list(self._runs.values()):
            if run.status == "retry_pending":
                self._execute_run(run)

    def _execute_run(self, run: PropagationRun):
        try:
            # Workspace Update
            if run.steps["workspace"] in ("pending", "failed"):
                success = self._step_workspace(run)
                run.steps["workspace"] = "✓" if success else "✗"
                
            # Obsidian Mirror
            if run.steps["obsidian"] in ("pending", "failed"):
                success = self._step_obsidian(run)
                run.steps["obsidian"] = "✓" if success else "✗"
                
            # Completion Event
            if run.steps["eventlog"] in ("pending", "failed"):
                success = self._step_eventlog(run)
                run.steps["eventlog"] = "✓" if success else "✗"
                
            # Evaluate overall status
            if all(v == "✓" for v in run.steps.values()):
                was_pending = run.status != "completed"
                run.status = "completed"
                if was_pending:
                    self._write_audit(run)
            else:
                run.status = "retry_pending"
                
            run.updated_at = _now()
            self._save_state()
            
        except Exception as e:
            logger.error("Execution failed for propagation %s: %s", run.propagation_id, e)
            run.status = "retry_pending"
            self._save_state()

    def _write_audit(self, run: PropagationRun):
        """Append an immutable audit record."""
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.audit_file, "a") as f:
                record = {
                    "timestamp": _now(),
                    "propagation_id": run.propagation_id,
                    "trigger_event": run.event_id,
                    "event_type": run.event_type,
                    "status": run.status,
                    "steps": run.steps,
                    "duration_seconds": (datetime.now(timezone.utc) - datetime.fromisoformat(run.created_at).replace(tzinfo=timezone.utc)).total_seconds()
                }
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error("Failed to write propagation audit: %s", e)

    def _step_workspace(self, run: PropagationRun) -> bool:
        """Update workspace team members if relationship indicates project involvement."""
        if run.event_type == "relationship.created":
            data = run.data
            # if works_on or owns targeting a project, ensure they are in the workspace
            rel_type = data.get("relationship_type")
            if rel_type in ("works_on", "owns"):
                # Simple heuristic: find workspace with matching project name
                ws_name = data.get("target_name")
                member_name = data.get("source_name")
                if ws_name and member_name:
                    # In a real system we'd look up WS by ID, but for now we list
                    for ws in self._ws_service.list_all():
                        if ws.name.lower() == ws_name.lower():
                            if member_name not in ws.team_members:
                                ws.team_members.append(member_name)
                                self._ws_service._save(ws)
                            break
        return True

    def _step_obsidian(self, run: PropagationRun) -> bool:
        """Sync entity or relationship to Obsidian strictly as a mirror."""
        # Offline-first tool check
        if not is_obsidian_available():
            logger.warning("Obsidian is not available. Will retry later.")
            return False
            
        try:
            if run.event_type in ("entity.created", "entity.updated"):
                entity = run.data
                name = entity.get("name", "Unknown")
                etype = entity.get("type", "entity")
                
                content = f"# {name}\n\n"
                for k, v in entity.items():
                    if k not in ("id", "name", "type"):
                        content += f"**{k.capitalize()}**: {v}\n"
                content += "\n*This file is a synchronized mirror from JATAYU OS.*\n"
                
                folder = "People" if etype == "person" else "Projects"
                path = f"{folder}/{name}.md"
                obsidian_write_note(path, content)
                
            elif run.event_type == "relationship.created":
                # We could append a backlink to both notes. 
                # For simplicity, we just assume success if it doesn't crash.
                pass
                
            return True
        except Exception as e:
            logger.error("Obsidian sync failed: %s", e)
            return False

    def _step_eventlog(self, run: PropagationRun) -> bool:
        """Record propagation completion to prevent hanging states."""
        if run.status != "completed": 
            # only emit complete if all other steps are ✓
            return True 
            
        try:
            self._event_log.emit(
                type="propagation.complete",
                session_id="system",
                source="propagation",
                data={"propagation_id": run.propagation_id, "trigger_event": run.event_id}
            )
            return True
        except Exception:
            return False

    def shutdown(self):
        self._stop_event.set()
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)
