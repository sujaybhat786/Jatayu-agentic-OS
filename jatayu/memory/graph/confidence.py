"""Memory Confidence Service."""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from jatayu.config import get_config
from jatayu.memory.graph.models import ConfidenceRecord, _now

logger = logging.getLogger(__name__)

# Constants
DECAY_RATE_PER_DAY = 0.05
MAX_CONFIDENCE = 1.0
MIN_CONFIDENCE = 0.1
VERIFIED_CONFIDENCE = 1.0

class MemoryConfidenceService:
    """Manages confidence, verification, and decay for flat facts and inferred memories."""
    
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or get_config()["data_dir"])
        self.path = self.data_dir / "memory_confidence.json"
        self._records: dict[str, ConfidenceRecord] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    self._records = {k: ConfidenceRecord.from_dict(v) for k, v in data.items()}
            except Exception as e:
                logger.error("Failed to load confidence records: %s", e)
                self._records = {}
                
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, "w") as f:
                data = {k: v.to_dict() for k, v in self._records.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save confidence records: %s", e)

    def init_record(self, memory_id: str, source: str = "inferred", confidence: float = 0.5) -> ConfidenceRecord:
        if memory_id in self._records:
            return self._records[memory_id]
            
        record = ConfidenceRecord(
            memory_id=memory_id,
            confidence=confidence,
            source=source
        )
        self._records[memory_id] = record
        self._save()
        return record

    def get_record(self, memory_id: str) -> ConfidenceRecord | None:
        return self._records.get(memory_id)

    def record_usage(self, memory_id: str):
        """Increase confidence slightly when a memory is used."""
        record = self._records.get(memory_id)
        if not record:
            return
            
        record.times_used += 1
        record.last_used_at = _now()
        
        # Boost confidence asymptotically towards max
        if not record.verified:
            boost = (MAX_CONFIDENCE - record.confidence) * 0.1
            record.confidence = min(MAX_CONFIDENCE, record.confidence + boost)
            
        record.updated_at = _now()
        self._save()

    def verify(self, memory_id: str):
        """Mark a memory as explicitly verified by the user."""
        record = self._records.get(memory_id)
        if not record:
            record = self.init_record(memory_id)
            
        record.verified = True
        record.confidence = VERIFIED_CONFIDENCE
        record.updated_at = _now()
        self._save()

    def apply_decay(self) -> list[str]:
        """Apply time-based decay to unverified inferred memories.
        Returns list of memory_ids that fell below MIN_CONFIDENCE (should be forgotten).
        """
        now = datetime.now(timezone.utc)
        to_forget = []
        
        for memory_id, record in self._records.items():
            if record.verified or record.source == "explicit_user":
                continue
                
            try:
                updated = datetime.fromisoformat(record.updated_at)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                
                days_since = (now - updated).days
                if days_since > 0:
                    decay = days_since * DECAY_RATE_PER_DAY
                    record.confidence = max(0.0, record.confidence - decay)
                    record.updated_at = _now()
                    
                    if record.confidence < MIN_CONFIDENCE:
                        to_forget.append(memory_id)
            except Exception:
                pass
                
        if to_forget:
            # We don't delete them here, we just report them so the store can delete
            self._save()
            
        return to_forget
