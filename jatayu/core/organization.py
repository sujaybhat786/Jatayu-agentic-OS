"""Organization model — multi-tenant readiness.

For Phase 2, JATAYU runs with a single default organization (personal use).
Every internal object is scoped to an organization so the architecture is
ready for commercial multi-tenant deployment without migration.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config


@dataclass
class Organization:
    """Represents an organization (tenant) in JATAYU.

    All data, agents, integrations, and permissions belong to an org.
    """

    id: str
    name: str
    data_dir: str                        # Isolated data directory
    created_at: str = ""
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "data_dir": self.data_dir,
            "created_at": self.created_at,
            "settings": self.settings,
        }


# ── Default Organization (singleton for V1) ──

_default_org: Organization | None = None


def get_current_org() -> Organization:
    """Return the current organization.

    For V1 (personal use), this always returns the default organization.
    In future multi-tenant deployments, this will resolve from the
    request context (JWT, session, etc.).
    """
    global _default_org
    if _default_org is not None:
        return _default_org

    config = get_config()
    data_dir = config["data_dir"]

    # Load or create org metadata
    org_path = Path(data_dir) / "organization.json"
    if org_path.exists():
        with open(org_path) as f:
            data = json.load(f)
        _default_org = Organization(**data)
    else:
        _default_org = Organization(
            id=uuid.uuid4().hex[:12],
            name=config.get("assistant_name", "Jatayu") + " Personal",
            data_dir=data_dir,
            created_at=datetime.now().isoformat(timespec="seconds"),
            settings={
                "model": config.get("model", "gemini-3.5-flash"),
                "voice": config.get("elevenlabs_voice", "Rachel"),
                "proactive": False,
            },
        )
        # Persist
        org_path.parent.mkdir(parents=True, exist_ok=True)
        with open(org_path, "w") as f:
            json.dump(_default_org.to_dict(), f, indent=2)

    return _default_org


def reset_org() -> None:
    """Clear cached org (for tests)."""
    global _default_org
    _default_org = None
