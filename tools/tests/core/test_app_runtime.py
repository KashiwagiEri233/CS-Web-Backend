"""Process-wide application runtime guard tests."""

import pytest
from fastapi import FastAPI

from app.core.app_runtime import ProcessRuntimeGuard


def test_runtime_guard_rejects_concurrent_applications():
    guard = ProcessRuntimeGuard()
    first = FastAPI()
    second = FastAPI()

    guard.acquire(first)

    with pytest.raises(RuntimeError, match="one active FastAPI application"):
        guard.acquire(second)

    guard.release(first)
    guard.acquire(second)


def test_runtime_guard_ignores_release_by_non_owner():
    guard = ProcessRuntimeGuard()
    owner = FastAPI()
    other = FastAPI()

    guard.acquire(owner)
    guard.release(other)

    with pytest.raises(RuntimeError, match="one active FastAPI application"):
        guard.acquire(other)
