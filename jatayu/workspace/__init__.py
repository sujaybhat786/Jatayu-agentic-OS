"""JATAYU Workspace Intelligence Layer.

Exported public surface:
    WorkspaceService    — CRUD for project workspaces
    FastCapture         — intent-gated message classifier
    WorkspaceHealth     — health calculation (pure, no I/O)
    TimelineRecorder    — EventLog subscriber
    DailyBriefAggregator — morning brief generator
    SuggestionEngine    — proactive stale/overdue detection

All services are optional-injected.  Nothing in this package imports
from jatayu.pipeline — it reads BrainState only via the snapshot.
"""

from jatayu.workspace.models import (
    Workspace,
    WorkspaceTask,
    WorkspaceNote,
    WorkspaceMeeting,
    TimelineEntry,
    WorkspaceHealth,
    TaskStatus,
    NoteType,
    CaptureItem,
    CaptureType,
    SuggestionItem,
    DailyBrief,
)
from jatayu.workspace.service import WorkspaceService
from jatayu.workspace.fast_capture import FastCapture
from jatayu.workspace.health import WorkspaceHealthCalculator
from jatayu.workspace.timeline import TimelineRecorder
from jatayu.workspace.daily_brief import DailyBriefAggregator
from jatayu.workspace.suggestions import SuggestionEngine

__all__ = [
    "Workspace",
    "WorkspaceTask",
    "WorkspaceNote",
    "WorkspaceMeeting",
    "TimelineEntry",
    "WorkspaceHealth",
    "TaskStatus",
    "NoteType",
    "CaptureItem",
    "CaptureType",
    "SuggestionItem",
    "DailyBrief",
    "WorkspaceService",
    "FastCapture",
    "WorkspaceHealthCalculator",
    "TimelineRecorder",
    "DailyBriefAggregator",
    "SuggestionEngine",
]
