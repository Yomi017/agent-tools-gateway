from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from toolhub.api import create_app
from toolhub.backends.docling import DoclingClient
from toolhub.config import Settings
from toolhub.errors import OutputExistsError, UpstreamError
from toolhub.tools.docling.backend import check_file, convert_file


@pytest.mark.asyncio
async def test_docling_client_health_reads_version(docling_settings) -> None:
    runtime = docling_settings.docling()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["X-API-Key"] == runtime.api_key
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/version":
            return httpx.Response(
                200,
                json={"name": "Docling Serve", "version": "1.16.1"},
            )
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    client = DoclingClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert calls == ["/health", "/version"]
    assert payload["reachable"] is True
    assert payload["health"]["status"] == "ok"
    assert payload["version"]["version"] == "1.16.1"


@pytest.mark.asyncio
async def test_docling_client_health_keeps_reachable_when_version_forbidden(
    docling_settings,
) -> None:
    runtime = docling_settings.docling()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/version":
            return httpx.Response(403, json={"detail": "Forbidden"})
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    client = DoclingClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert calls == ["/health", "/version"]
    assert payload["reachable"] is True
    assert payload["status_code"] == 200
    assert "version" not in payload
    assert payload["version_status_code"] == 403
    assert "Forbidden" in payload["version_body_preview"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 404, 500])
async def test_docling_client_health_rejects_non_2xx_health(
    docling_settings,
    status_code: int,
) -> None:
    runtime = docling_settings.docling()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(status_code, json={"detail": "nope"})
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    client = DoclingClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert calls == ["/health"]
    assert payload["reachable"] is False
    assert payload["status_code"] == status_code
    assert payload["health"]["detail"] == "nope"
    assert "version" not in payload


@pytest.mark.asyncio
async def test_docling_client_convert_file_async_flow(docling_settings) -> None:
    runtime = docling_settings.docling()
    input_path = runtime.allowed_input_roots[0] / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            assert request.headers["X-API-Key"] == runtime.api_key
            assert b'name="to_formats"' in request.content
            assert b"\r\nmd\r\n" in request.content
            return httpx.Response(200, json={"task_id": "task-123", "task_status": "pending"})
        if request.url.path == "/v1/status/poll/task-123":
            return httpx.Response(200, json={"task_id": "task-123", "task_status": "success"})
        if request.url.path == "/v1/result/task-123":
            return httpx.Response(
                200,
                json={"document": {"filename": "sample.pdf", "md_content": "# Parsed\n"}},
            )
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    client = DoclingClient(runtime, transport=httpx.MockTransport(handler))

    task_id, content, duration_ms = await client.convert_file(input_path, output_format="md")

    assert task_id == "task-123"
    assert content == b"# Parsed\n"
    assert duration_ms >= 0


@pytest.mark.asyncio
async def test_docling_client_rejects_multifile_result(docling_settings) -> None:
    runtime = docling_settings.docling()
    input_path = runtime.allowed_input_roots[0] / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "task-zip"})
        if request.url.path == "/v1/status/poll/task-zip":
            return httpx.Response(200, json={"task_status": "success"})
        if request.url.path == "/v1/result/task-zip":
            return httpx.Response(
                200,
                json={"document": {"files": [{"name": "part-1.md"}], "md_content": "# Parsed\n"}},
            )
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    client = DoclingClient(runtime, transport=httpx.MockTransport(handler))

    with pytest.raises(UpstreamError):
        await client.convert_file(input_path, output_format="md")


@pytest.mark.asyncio
async def test_docling_backend_check_uses_input_stem_by_default(docling_settings) -> None:
    runtime = docling_settings.docling()
    input_path = runtime.allowed_input_roots[0] / "lecture-notes.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")

    payload = await check_file(
        input_path=str(input_path),
        output_format="text",
        output_dir=str(runtime.allowed_output_roots[0]),
        settings=docling_settings,
    )

    assert payload.planned_output_path.endswith("/lecture-notes.txt")
    assert payload.effective_options["output_format"] == "text"


@pytest.mark.asyncio
async def test_docling_backend_convert_writes_output_file(
    docling_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, _runtime) -> None:
            pass

        async def convert_file(self, *_args, **_kwargs):
            return ("task-456", b"# Parsed\n", 12)

    runtime = docling_settings.docling()
    input_path = runtime.allowed_input_roots[0] / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")
    monkeypatch.setattr("toolhub.tools.docling.backend.DoclingClient", FakeClient)

    payload = await convert_file(
        input_path=str(input_path),
        output_format="md",
        output_dir=str(runtime.allowed_output_roots[0]),
        filename_stem="lecture-summary",
        overwrite=True,
        settings=docling_settings,
    )

    output_path = runtime.allowed_output_roots[0] / "lecture-summary.md"
    assert payload.task_id == "task-456"
    assert payload.output.filename == "lecture-summary.md"
    assert output_path.read_text(encoding="utf-8") == "# Parsed\n"


@pytest.mark.asyncio
async def test_docling_backend_output_exists_without_overwrite(docling_settings) -> None:
    runtime = docling_settings.docling()
    input_path = runtime.allowed_input_roots[0] / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")
    existing = runtime.allowed_output_roots[0] / "sample.md"
    existing.write_text("old", encoding="utf-8")

    with pytest.raises(OutputExistsError):
        await check_file(
            input_path=str(input_path),
            output_format="md",
            output_dir=str(runtime.allowed_output_roots[0]),
            overwrite=False,
            settings=docling_settings,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"input_path": 123, "output_format": "md"},
        {"input_path": "/tmp/sample.pdf", "output_format": "md", "include_images": 1},
        {"input_path": "/tmp/sample.pdf", "output_format": 123},
    ],
)
def test_docling_invalid_payload_types_return_422(payload) -> None:
    app = create_app(Settings(backends={"docling": {"enabled": True}}))
    client = TestClient(app)

    response = client.post("/v1/docling/check", json=payload)

    assert response.status_code == 422
