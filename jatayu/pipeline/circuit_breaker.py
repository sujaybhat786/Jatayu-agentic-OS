"""Circuit Breaker — protects against repeatedly failing external services.

After `failure_threshold` consecutive failures, the circuit opens and
all requests are bypassed for `reset_seconds`. On the first success
after the cooldown, the circuit closes again.

Usage:
    breaker = CircuitBreaker("anythingllm", failure_threshold=3, reset_seconds=300)

    if breaker.is_open():
        # use fallback
        return vault_search(query)
    try:
        result = anythingllm_search(query)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        return vault_search(query)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """Thread-safe circuit breaker for a named external service.

    Args:
        name:              Human-readable service name (for logging).
        failure_threshold: Consecutive failures before opening (default 3).
        reset_seconds:     How long to stay open before half-open probe (default 300 s = 5 min).
    """
    name: str
    failure_threshold: int = 3
    reset_seconds: float = 300.0

    _consecutive_failures: int = field(default=0, init=False)
    _open_until: float = field(default=0.0, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_successes: int = field(default=0, init=False)

    def is_open(self) -> bool:
        """Return True if the circuit is open (requests should be bypassed)."""
        if self._open_until > 0 and time.monotonic() < self._open_until:
            return True
        if self._open_until > 0 and time.monotonic() >= self._open_until:
            # Cooldown expired — move to half-open (allow one probe)
            logger.info(
                "CircuitBreaker[%s]: cooldown expired, allowing probe request.",
                self.name,
            )
            self._open_until = 0.0
        return False

    def record_success(self) -> None:
        """Record a successful call. Resets failure counter and closes circuit."""
        self._total_successes += 1
        if self._consecutive_failures > 0:
            logger.info(
                "CircuitBreaker[%s]: recovered after %d failure(s).",
                self.name, self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        """Record a failed call. Opens circuit after threshold is reached."""
        self._consecutive_failures += 1
        self._total_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._open_until = time.monotonic() + self.reset_seconds
            logger.warning(
                "CircuitBreaker[%s]: opened after %d consecutive failures. "
                "Bypassing for %.0f s.",
                self.name, self._consecutive_failures, self.reset_seconds,
            )

    def status(self) -> dict:
        """Return current circuit status (for /api/status or health checks)."""
        open_remaining = max(0.0, self._open_until - time.monotonic())
        return {
            "service":              self.name,
            "state":                "open" if self.is_open() else "closed",
            "consecutive_failures": self._consecutive_failures,
            "total_failures":       self._total_failures,
            "total_successes":      self._total_successes,
            "open_remaining_s":     round(open_remaining, 1),
        }


# ── Singleton registry ────────────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    reset_seconds: float = 300.0,
) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            reset_seconds=reset_seconds,
        )
    return _breakers[name]


def all_statuses() -> list[dict]:
    """Return status dicts for all registered breakers."""
    return [b.status() for b in _breakers.values()]
