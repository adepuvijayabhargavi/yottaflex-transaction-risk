"""In-memory login throttling for repeated failed authentication attempts."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from flask import current_app


@dataclass
class _AttemptState:
    """Failure timestamps and lockout deadline for one client key."""

    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


class LoginRateLimiter:
    """Track failed sign-ins per client and temporarily block abusive clients.

    State is held in process memory. It is intentionally simple and resets
    whenever the worker restarts, so multi-process deployments should use a
    shared limiter such as a reverse-proxy or Redis-backed solution.
    """

    def __init__(self) -> None:
        self._states: dict[str, _AttemptState] = {}
        self._lock = Lock()

    def _settings(self) -> tuple[int, int, int]:
        max_attempts = int(current_app.config.get("YTF_LOGIN_MAX_ATTEMPTS", 5))
        window_seconds = int(current_app.config.get("YTF_LOGIN_WINDOW_SECONDS", 300))
        lockout_seconds = int(current_app.config.get("YTF_LOGIN_LOCKOUT_SECONDS", 900))
        return max_attempts, window_seconds, lockout_seconds

    @staticmethod
    def _prune(state: _AttemptState, now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while state.failures and state.failures[0] <= cutoff:
            state.failures.popleft()

    def is_locked(self, key: str) -> bool:
        """Return True when the client key is currently in lockout."""

        _, window_seconds, _ = self._settings()
        now = time.monotonic()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return False

            if state.locked_until and state.locked_until <= now:
                state.failures.clear()
                state.locked_until = 0.0
                return False

            if state.locked_until > now:
                return True

            self._prune(state, now, window_seconds)
            return False

    def record_failure(self, key: str) -> bool:
        """Record a failure and return True if this attempt triggers lockout."""

        max_attempts, window_seconds, lockout_seconds = self._settings()
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, _AttemptState())
            if state.locked_until and state.locked_until <= now:
                state.failures.clear()
                state.locked_until = 0.0

            self._prune(state, now, window_seconds)
            state.failures.append(now)

            if len(state.failures) >= max_attempts:
                state.locked_until = now + lockout_seconds
                return True
            return False

    def reset(self, key: str) -> None:
        """Clear failures and lockout for a client after a successful sign-in."""

        with self._lock:
            self._states.pop(key, None)

    def clear(self) -> None:
        """Remove all tracked client state. Intended for tests and shutdown."""

        with self._lock:
            self._states.clear()


def get_login_limiter() -> LoginRateLimiter:
    """Return the application-scoped login limiter, creating it lazily."""

    limiter = current_app.extensions.get("login_limiter")
    if not isinstance(limiter, LoginRateLimiter):
        limiter = LoginRateLimiter()
        current_app.extensions["login_limiter"] = limiter
    return limiter
