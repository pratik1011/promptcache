"""Per-provider circuit breaker and retry backoff.

Kept in-process and thread-safe: a provider that fails repeatedly is parked
briefly so the gateway stops hammering it and falls through to healthy
providers. This is a cheap local safeguard; a distributed breaker would use
Redis and is a documented follow-up.
"""
import threading
import time

DEFAULT_FAIL_THRESHOLD = 3
DEFAULT_OPEN_SECONDS = 30
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 8.0


class CircuitBreaker:
    """Tracks consecutive failures per provider id and opens after a threshold."""

    def __init__(self, fail_threshold: int = DEFAULT_FAIL_THRESHOLD, open_seconds: int = DEFAULT_OPEN_SECONDS):
        self.fail_threshold = fail_threshold
        self.open_seconds = open_seconds
        self._failures: dict[str, int] = {}
        self._opened_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, provider_id: str) -> bool:
        with self._lock:
            until = self._opened_until.get(provider_id, 0.0)
            now = time.monotonic()
            if until and now > until:
                # Half-open: allow a probe and reset the failure counter.
                self._opened_until.pop(provider_id, None)
                self._failures[provider_id] = 0
            return self._opened_until.get(provider_id, 0.0) <= now

    def record_success(self, provider_id: str) -> None:
        with self._lock:
            self._failures[provider_id] = 0
            self._opened_until.pop(provider_id, None)

    def record_failure(self, provider_id: str) -> None:
        with self._lock:
            failures = self._failures.get(provider_id, 0) + 1
            self._failures[provider_id] = failures
            if failures >= self.fail_threshold:
                self._opened_until[provider_id] = time.monotonic() + self.open_seconds

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._opened_until.clear()


def next_delay(attempt: int, base: float = DEFAULT_BACKOFF_BASE, cap: float = DEFAULT_BACKOFF_CAP) -> float:
    """Exponential backoff delay for retry attempt index (0-based), capped."""
    return min(cap, base * (2 ** attempt))


breaker = CircuitBreaker()
