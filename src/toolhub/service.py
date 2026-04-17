from __future__ import annotations

from .config import Settings, get_settings
from .errors import error_payload
from .models import HealthResponse
from .registry import collect_backend_health


def _settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


async def health(settings: Settings | None = None) -> HealthResponse:
    runtime = _settings(settings)
    return HealthResponse(backends=await collect_backend_health(runtime))


async def health_payload(settings: Settings | None = None) -> dict[str, object]:
    try:
        return (await health(settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)
