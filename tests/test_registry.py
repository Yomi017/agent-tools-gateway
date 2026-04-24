from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from toolhub.api import _auth_dependency, create_app
from toolhub.config import Settings
from toolhub.mcp_server import _http_auth_app, create_mcp
from toolhub.models import HealthResponse
from toolhub.registry import collect_backend_health, get_enabled_backends
from toolhub.service import health_payload


def test_registry_discovers_enabled_convertx_backend(settings) -> None:
    backends = get_enabled_backends(settings)

    assert [backend.key for backend in backends] == ["convertx"]


def test_registry_discovers_enabled_webcapture_backend(webcapture_settings) -> None:
    backends = get_enabled_backends(webcapture_settings)

    assert [backend.key for backend in backends] == ["convertx", "webcapture"]


def test_registry_discovers_enabled_docling_backend(docling_settings) -> None:
    backends = get_enabled_backends(docling_settings)

    assert [backend.key for backend in backends] == ["convertx", "docling"]


def test_registry_discovers_enabled_searxng_backend(searxng_settings) -> None:
    backends = get_enabled_backends(searxng_settings)

    assert [backend.key for backend in backends] == ["convertx", "searxng"]


def test_registry_skips_disabled_backend() -> None:
    settings = Settings(backends={"convertx": {"enabled": False}})

    assert get_enabled_backends(settings) == []


def test_registry_skips_backend_when_is_enabled_fails(monkeypatch) -> None:
    class BrokenEnabledBackend:
        key = "broken_enabled"

        def is_enabled(self, settings) -> bool:
            raise RuntimeError("enabled boom")

        async def health(self, settings) -> dict[str, object]:
            return {"reachable": True}

    settings = Settings(backends={"convertx": {"enabled": False}})
    monkeypatch.setattr("toolhub.registry.BACKENDS", (BrokenEnabledBackend(),))

    assert get_enabled_backends(settings) == []


def test_mcp_registers_namespaced_and_legacy_convertx_tools(settings) -> None:
    mcp = create_mcp(settings)
    names = set(mcp._tool_manager._tools)

    assert {
        "toolhub_health",
        "convertx_health",
        "convertx_list_targets",
        "convertx_convert_file",
        "convertx_convert_batch",
        "list_conversion_targets",
        "convert_file",
        "convert_batch",
    }.issubset(names)


def test_mcp_registers_webcapture_tools(webcapture_settings) -> None:
    mcp = create_mcp(webcapture_settings)
    names = set(mcp._tool_manager._tools)

    assert {
        "webcapture_health",
        "webcapture_check_url",
        "webcapture_capture_url",
        "check_webpage_capture",
        "capture_webpage",
    }.issubset(names)


def test_mcp_registers_docling_tools(docling_settings) -> None:
    mcp = create_mcp(docling_settings)
    names = set(mcp._tool_manager._tools)

    assert {
        "docling_health",
        "docling_check_file",
        "docling_convert_file",
    }.issubset(names)


def test_mcp_registers_searxng_tools(searxng_settings) -> None:
    mcp = create_mcp(searxng_settings)
    names = set(mcp._tool_manager._tools)

    assert {
        "searxng_health",
        "searxng_search",
    }.issubset(names)


@pytest.mark.asyncio
async def test_health_route_aggregates_backend_health(settings, monkeypatch) -> None:
    async def fake_health(_settings=None):
        return HealthResponse(
            backends={"convertx": {"reachable": True, "base_url": "http://convertx.test"}}
        )

    monkeypatch.setattr("toolhub.api.health", fake_health)

    app = create_app(settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    response = await route.endpoint()

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["backends"]["convertx"]["reachable"] is True


@pytest.mark.asyncio
async def test_health_route_includes_webcapture_backend(webcapture_settings, monkeypatch) -> None:
    async def fake_health(_settings=None):
        return HealthResponse(
            backends={
                "convertx": {"reachable": True, "base_url": "http://convertx.test"},
                "webcapture": {
                    "reachable": True,
                    "base_url": "http://browserless.test",
                    "isAvailable": True,
                    "running": 0,
                    "queued": 0,
                },
            }
        )

    monkeypatch.setattr("toolhub.api.health", fake_health)

    app = create_app(webcapture_settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    response = await route.endpoint()

    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["backends"]["webcapture"]["isAvailable"] is True


@pytest.mark.asyncio
async def test_health_route_includes_unreachable_webcapture_backend(webcapture_settings, monkeypatch) -> None:
    async def fake_health(_settings=None):
        return HealthResponse(
            backends={
                "convertx": {"reachable": True, "base_url": "http://convertx.test"},
                "webcapture": {
                    "reachable": False,
                    "base_url": "http://browserless.test",
                    "status_code": 401,
                    "body_preview": "Unauthorized",
                },
            }
        )

    monkeypatch.setattr("toolhub.api.health", fake_health)

    app = create_app(webcapture_settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    response = await route.endpoint()

    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["backends"]["webcapture"]["reachable"] is False
    assert payload["backends"]["webcapture"]["status_code"] == 401


@pytest.mark.asyncio
async def test_health_route_includes_docling_backend(docling_settings, monkeypatch) -> None:
    async def fake_health(_settings=None):
        return HealthResponse(
            backends={
                "convertx": {"reachable": True, "base_url": "http://convertx.test"},
                "docling": {
                    "reachable": True,
                    "base_url": "http://docling.test",
                    "version": {"name": "Docling Serve", "version": "1.16.1"},
                },
            }
        )

    monkeypatch.setattr("toolhub.api.health", fake_health)

    app = create_app(docling_settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    response = await route.endpoint()

    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["backends"]["docling"]["reachable"] is True
    assert payload["backends"]["docling"]["version"]["version"] == "1.16.1"


@pytest.mark.asyncio
async def test_health_route_includes_searxng_backend(searxng_settings, monkeypatch) -> None:
    async def fake_health(_settings=None):
        return HealthResponse(
            backends={
                "convertx": {"reachable": True, "base_url": "http://convertx.test"},
                "searxng": {
                    "reachable": True,
                    "base_url": "http://searxng.test",
                    "instance_name": "Toolhub Search",
                    "enabled_engines": ["duckduckgo", "brave"],
                },
            }
        )

    monkeypatch.setattr("toolhub.api.health", fake_health)

    app = create_app(searxng_settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    response = await route.endpoint()

    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["backends"]["searxng"]["reachable"] is True
    assert payload["backends"]["searxng"]["enabled_engines"] == ["duckduckgo", "brave"]


@pytest.mark.asyncio
async def test_collect_backend_health_degrades_per_backend(monkeypatch) -> None:
    class HealthyBackend:
        key = "healthy"

        def is_enabled(self, settings) -> bool:
            return True

        async def health(self, settings) -> dict[str, object]:
            return {"reachable": True}

    class BrokenBackend:
        key = "broken"

        def is_enabled(self, settings) -> bool:
            return True

        async def health(self, settings) -> dict[str, object]:
            raise RuntimeError("boom")

    settings = Settings(backends={"convertx": {"enabled": False}})
    monkeypatch.setattr("toolhub.registry.BACKENDS", (HealthyBackend(), BrokenBackend()))

    payload = await collect_backend_health(settings)

    assert payload["healthy"] == {"reachable": True}
    assert payload["broken"]["ok"] is False
    assert payload["broken"]["error"]["code"] == "internal_error"


@pytest.mark.asyncio
async def test_collect_backend_health_degrades_when_is_enabled_fails(monkeypatch) -> None:
    class BrokenEnabledBackend:
        key = "broken_enabled"

        def is_enabled(self, settings) -> bool:
            raise RuntimeError("enabled boom")

        async def health(self, settings) -> dict[str, object]:
            return {"reachable": True}

    settings = Settings(backends={"convertx": {"enabled": False}})
    monkeypatch.setattr("toolhub.registry.BACKENDS", (BrokenEnabledBackend(),))

    payload = await collect_backend_health(settings)

    assert payload["broken_enabled"]["ok"] is False
    assert payload["broken_enabled"]["error"]["code"] == "internal_error"


@pytest.mark.asyncio
async def test_toolhub_health_payload_stays_ok_with_backend_failure(monkeypatch) -> None:
    class BrokenBackend:
        key = "broken"

        def is_enabled(self, settings) -> bool:
            return True

        async def health(self, settings) -> dict[str, object]:
            raise RuntimeError("boom")

    settings = Settings(backends={"convertx": {"enabled": False}})
    monkeypatch.setattr("toolhub.registry.BACKENDS", (BrokenBackend(),))

    payload = await health_payload(settings)

    assert payload["ok"] is True
    assert payload["backends"]["broken"]["ok"] is False
    assert payload["backends"]["broken"]["error"]["code"] == "internal_error"


@pytest.mark.asyncio
async def test_mcp_http_no_token_preserves_current_behavior(settings) -> None:
    async def downstream(scope, receive, send) -> None:
        await JSONResponse({"ok": True}, status_code=200)(scope, receive, send)

    transport = httpx.ASGITransport(app=_http_auth_app(downstream, settings.auth_token))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/mcp")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mcp_http_rejects_missing_or_wrong_bearer_token(settings) -> None:
    protected = settings.model_copy(update={"auth_token": "secret-token"})

    async def downstream(scope, receive, send) -> None:
        await JSONResponse({"ok": True}, status_code=200)(scope, receive, send)

    transport = httpx.ASGITransport(app=_http_auth_app(downstream, protected.auth_token))

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.get("/mcp")
        wrong = await client.get("/mcp", headers={"Authorization": "Bearer wrong-token"})

    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_mcp_http_accepts_matching_bearer_token(settings) -> None:
    protected = settings.model_copy(update={"auth_token": "secret-token"})

    async def downstream(scope, receive, send) -> None:
        await JSONResponse({"ok": True}, status_code=200)(scope, receive, send)

    transport = httpx.ASGITransport(app=_http_auth_app(downstream, protected.auth_token))

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/mcp", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rest_and_mcp_share_same_bearer_token(settings) -> None:
    protected = settings.model_copy(update={"auth_token": "shared-token"})
    rest_auth = _auth_dependency(protected.auth_token)

    async def downstream(scope, receive, send) -> None:
        await JSONResponse({"ok": True}, status_code=200)(scope, receive, send)

    mcp_transport = httpx.ASGITransport(app=_http_auth_app(downstream, protected.auth_token))

    with pytest.raises(HTTPException) as denied:
        rest_auth()
    rest_auth("Bearer shared-token")

    async with httpx.AsyncClient(transport=mcp_transport, base_url="http://testserver") as client:
        mcp_allowed = await client.get("/mcp", headers={"Authorization": "Bearer shared-token"})

    assert denied.value.status_code == 401
    assert mcp_allowed.status_code == 200
