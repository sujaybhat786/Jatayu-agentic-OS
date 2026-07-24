"""Cost Ledger — append-only per-call cost tracking.

Writes one JSONL line after every LLM call containing:
  timestamp, session_id, model, tokens_in, tokens_out, est_usd

Exposes:
  CostLedger.record(...)    — called after each brain.send()
  CostLedger.today_summary()— returns dict with today's totals
  GET /api/cost-today       — served from server.py

Budget guard:
  CostLedger.should_downgrade(intent) — True when daily soft cap exceeded
  and intent is on the Pro model. Triggers Flash fallback with a log warning.

Cost rates ($/1M tokens) are read from config.yaml model_costs.
Unknown models default to Flash rates (conservative estimate).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jatayu.config import get_config

logger = logging.getLogger(__name__)


# Default cost table (USD per 1M tokens) — updated from config.yaml at init
_DEFAULT_COSTS: dict[str, dict[str, float]] = {
    "gemini-3.5-flash":       {"in": 0.075,  "out": 0.30},
    "gemini-2.5-flash":       {"in": 0.075,  "out": 0.30},
    "gemini-3.1-pro-preview": {"in": 1.25,   "out": 5.00},
    "gemini-2.5-pro-preview": {"in": 1.25,   "out": 5.00},
    "gemini-exp-1206":        {"in": 1.25,   "out": 5.00},
    "qwen-local":             {"in": 0.0,    "out": 0.0},
}


class CostLedger:
    """Append-only cost tracker for every LLM call.

    Args:
        data_dir: The app data directory (e.g. "data/").
    """

    def __init__(self, data_dir: str) -> None:
        self._path = Path(data_dir) / "cost_ledger.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

        config = get_config()
        self._costs: dict[str, dict[str, float]] = dict(_DEFAULT_COSTS)
        for model, rates in config.get("model_costs", {}).items():
            try:
                self._costs[model] = {
                    "in":  float(rates.get("in_per_1m",  rates.get("in",  0.075))),
                    "out": float(rates.get("out_per_1m", rates.get("out", 0.30))),
                }
            except (TypeError, ValueError):
                pass  # keep the default

        budget_cfg = config.get("budget", {})
        self._daily_soft_cap: float = float(
            budget_cfg.get("daily_usd_soft_cap", 2.00)
        )

        # In-memory daily accumulator (reset on date change)
        self._today_date: str = self._today_str()
        self._today_in:   int = 0
        self._today_out:  int = 0
        self._today_usd:  float = 0.0

        # Load today's existing totals from the ledger file
        self._load_today_totals()

    # ── Public API ────────────────────────────────────────────────────────────

    def record(
        self,
        session_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        intent: str = "unknown",
        extra: dict[str, Any] | None = None,
    ) -> float:
        """Record one LLM call. Returns the estimated cost in USD."""
        rates = self._costs.get(model) or self._costs.get("gemini-3.5-flash")
        est_usd = (
            tokens_in  / 1_000_000 * rates["in"] +
            tokens_out / 1_000_000 * rates["out"]
        )

        entry = {
            "ts":        datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session":   session_id,
            "model":     model,
            "in":        tokens_in,
            "out":       tokens_out,
            "usd":       round(est_usd, 6),
            "intent":    intent,
        }
        if extra:
            entry.update(extra)

        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning("CostLedger: write failed: %s", e)

        # Update in-memory accumulator
        today = self._today_str()
        if today != self._today_date:
            self._today_date = today
            self._today_in = self._today_out = 0
            self._today_usd = 0.0
        self._today_in  += tokens_in
        self._today_out += tokens_out
        self._today_usd += est_usd

        if self._today_usd > self._daily_soft_cap * 0.9:
            logger.warning(
                "CostLedger: approaching daily cap — today=%.4f USD cap=%.2f",
                self._today_usd, self._daily_soft_cap,
            )

        return est_usd

    def should_downgrade(self, intent: str) -> bool:
        """Return True if the daily soft cap is exceeded.

        When True, Pro-model intents should fall back to Flash with a log warning.
        The user can override by explicitly asking to "use pro" / "use the better model".
        """
        today = self._today_str()
        if today != self._today_date:
            return False   # new day, counters reset
        exceeded = self._today_usd >= self._daily_soft_cap
        if exceeded:
            logger.warning(
                "CostLedger: soft cap exceeded (%.4f >= %.2f). "
                "Downgrading intent=%s from Pro to Flash.",
                self._today_usd, self._daily_soft_cap, intent,
            )
        return exceeded

    def today_summary(self) -> dict:
        """Return today's cost summary as a dict (for /api/cost-today)."""
        today = self._today_str()
        if today != self._today_date:
            self._today_date = today
            self._today_in = self._today_out = 0
            self._today_usd = 0.0
        return {
            "date":           today,
            "tokens_in":      self._today_in,
            "tokens_out":     self._today_out,
            "est_usd":        round(self._today_usd, 4),
            "soft_cap_usd":   self._daily_soft_cap,
            "cap_used_pct":   round(
                min(100.0, self._today_usd / self._daily_soft_cap * 100), 1
            ) if self._daily_soft_cap > 0 else 0.0,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _today_str() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _load_today_totals(self) -> None:
        """Scan the ledger file for today's existing entries."""
        today = self._today_str()
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("ts", "").startswith(today):
                            self._today_in  += entry.get("in",  0)
                            self._today_out += entry.get("out", 0)
                            self._today_usd += entry.get("usd", 0.0)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
