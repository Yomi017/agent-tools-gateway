from __future__ import annotations

from typing import Any

from .config import Settings, get_settings
from .errors import error_payload
from .tools.convertx.backend import BACKEND as CONVERTX_BACKEND
from .tools.webcapture.backend import BACKEND as WEBCAPTURE_BACKEND


BACKENDS = (CONVERTX_BACKEND, WEBCAPTURE_BACKEND)


def get_enabled_backends(settings: Settings | None = None) -> list[Any]:
    runtime = settings or get_settings()
    backends: list[Any] = []
    for backend in BACKENDS:
        try:
            if backend.is_enabled(runtime):
                backends.append(backend)
        except Exception:
            continue
    return backends


async def collect_backend_health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = settings or get_settings()
    results: dict[str, Any] = {}
    for backend in BACKENDS:
        try:
            enabled = backend.is_enabled(runtime)
        except Exception as exc:
            results[backend.key] = error_payload(exc)
            continue

        if not enabled:
            continue

        try:
            results[backend.key] = await backend.health(runtime)
        except Exception as exc:
            results[backend.key] = error_payload(exc)
    return results
