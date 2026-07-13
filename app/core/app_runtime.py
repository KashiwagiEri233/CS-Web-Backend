"""Process-wide application runtime ownership guard.

The framework keeps database, Redis, telemetry, and lifecycle registries at
module scope.  Until those resources become application-scoped, only one
FastAPI lifespan may be active in a process.
"""

from threading import Lock
from typing import Optional

from fastapi import FastAPI


class ProcessRuntimeGuard:
    """Reject concurrent application lifespans that would share global state."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active_application_id: Optional[int] = None

    def acquire(self, application: FastAPI) -> None:
        """Claim process resources for one application lifespan."""
        with self._lock:
            if self._active_application_id is not None:
                raise RuntimeError(
                    "Process resources already belong to an active application; "
                    "run one active FastAPI application per process"
                )
            self._active_application_id = id(application)

    def release(self, application: FastAPI) -> None:
        """Release resources if they are owned by ``application``."""
        with self._lock:
            if self._active_application_id == id(application):
                self._active_application_id = None


process_runtime_guard = ProcessRuntimeGuard()
