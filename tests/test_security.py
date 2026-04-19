from __future__ import annotations

import os
import socket
from pathlib import Path

import playwright.async_api as playwright_async_api
import pytest

from toolhub.errors import (
    FileTooLargeError,
    InvalidFilenameError,
    OutputExistsError,
    PathNotAllowedError,
    UrlNotAllowedError,
)
from toolhub.security import PathPolicy, WebCapturePathPolicy, validate_web_url
from toolhub.tools.webcapture.client import PlaywrightCaptureSession


def test_path_policy_accepts_global_settings(settings) -> None:
    runtime = settings.convertx()
    policy = PathPolicy(settings)

    assert policy.input_roots == [runtime.allowed_input_roots[0].resolve()]
    assert policy.output_roots == [runtime.allowed_output_roots[0].resolve()]


def test_input_file_allowed(settings) -> None:
    runtime = settings.convertx()
    path = runtime.allowed_input_roots[0] / "sample.txt"
    path.write_text("ok", encoding="utf-8")

    assert PathPolicy(runtime).validate_input_file(path) == path.resolve()


def test_input_file_rejects_outside_root(settings, tmp_path: Path) -> None:
    runtime = settings.convertx()
    path = tmp_path / "outside.txt"
    path.write_text("no", encoding="utf-8")

    with pytest.raises(PathNotAllowedError):
        PathPolicy(runtime).validate_input_file(path)


def test_input_file_rejects_symlink_escape(settings, tmp_path: Path) -> None:
    runtime = settings.convertx()
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    link = runtime.allowed_input_roots[0] / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not supported on this filesystem")

    with pytest.raises(PathNotAllowedError):
        PathPolicy(runtime).validate_input_file(link)


def test_output_dir_rejects_parent_escape(settings) -> None:
    runtime = settings.convertx()
    escaped = runtime.allowed_output_roots[0] / ".." / "elsewhere"

    with pytest.raises(PathNotAllowedError):
        PathPolicy(runtime).validate_output_dir(escaped)


def test_input_file_size_limit(settings) -> None:
    runtime = settings.convertx()
    path = runtime.allowed_input_roots[0] / "large.bin"
    path.write_bytes(b"abcd")
    limited = runtime.model_copy(update={"max_file_bytes": 3})

    with pytest.raises(FileTooLargeError):
        PathPolicy(limited).validate_input_file(path)


def test_validate_web_url_rejects_private_ipv4_literal() -> None:
    with pytest.raises(UrlNotAllowedError):
        validate_web_url("http://127.0.0.1:8000")


def test_validate_web_url_rejects_host_resolving_to_private_ip() -> None:
    def resolver(hostname: str, port: int | None):
        assert hostname == "internal.example"
        assert port == 443
        return ["10.0.0.5"]

    with pytest.raises(UrlNotAllowedError):
        validate_web_url(
            "https://internal.example",
            resolver=resolver,
        )


def test_validate_web_url_rejects_resolution_failure() -> None:
    def resolver(hostname: str, port: int | None):
        assert hostname == "host.docker.internal"
        raise socket.gaierror("name resolution failed")

    with pytest.raises(UrlNotAllowedError) as exc_info:
        validate_web_url(
            "https://host.docker.internal",
            resolver=resolver,
        )

    assert exc_info.value.details["reason"] == "resolution_failed"


def test_webcapture_output_dir_rejects_parent_escape(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()
    escaped = runtime.allowed_output_roots[0] / ".." / "elsewhere"

    with pytest.raises(PathNotAllowedError):
        WebCapturePathPolicy(runtime).validate_output_dir(escaped)


def test_webcapture_filename_stem_rejects_path_separators(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()

    with pytest.raises(InvalidFilenameError):
        WebCapturePathPolicy(runtime).validate_filename_stem("../escape")


def test_webcapture_output_exists_without_overwrite(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()
    policy = WebCapturePathPolicy(runtime)
    output_dir = runtime.allowed_output_roots[0]
    existing = output_dir / "example.pdf"
    existing.write_bytes(b"old")

    with pytest.raises(OutputExistsError):
        policy.build_output_path(
            normalized_url="https://example.com/",
            output_format="pdf",
            output_dir=str(output_dir),
            filename_stem="example",
            overwrite=False,
        )


@pytest.mark.asyncio
async def test_playwright_session_blocks_disallowed_document_request(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()
    session = PlaywrightCaptureSession(
        runtime,
        resolver=lambda hostname, port: ["127.0.0.1"] if hostname == "evil.test" else ["93.184.216.34"],
    )
    aborted: list[str] = []

    class FakeRequest:
        url = "http://evil.test/secret"
        resource_type = "document"

    class FakeRoute:
        request = FakeRequest()

        async def abort(self, reason: str) -> None:
            aborted.append(reason)

    await session._route_request(FakeRoute())

    assert aborted == ["blockedbyclient"]
    assert session.blocked_requests[0].resource_type == "document"


@pytest.mark.asyncio
async def test_playwright_session_blocks_disallowed_subresource_request(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()
    session = PlaywrightCaptureSession(
        runtime,
        resolver=lambda hostname, port: ["127.0.0.1"] if hostname == "evil.test" else ["93.184.216.34"],
    )
    aborted: list[str] = []

    class FakeRequest:
        url = "http://evil.test/asset.png"
        resource_type = "image"

    class FakeRoute:
        request = FakeRequest()

        async def abort(self, reason: str) -> None:
            aborted.append(reason)

    await session._route_request(FakeRoute())

    assert aborted == ["blockedbyclient"]
    assert session.blocked_requests[0].resource_type == "image"


@pytest.mark.asyncio
async def test_playwright_session_blocks_resolution_failure(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()

    def resolver(hostname: str, port: int | None):
        assert hostname == "host.docker.internal"
        raise socket.gaierror("name resolution failed")

    session = PlaywrightCaptureSession(runtime, resolver=resolver)
    aborted: list[str] = []

    class FakeRequest:
        url = "https://host.docker.internal/path"
        resource_type = "document"

    class FakeRoute:
        request = FakeRequest()

        async def abort(self, reason: str) -> None:
            aborted.append(reason)

    await session._route_request(FakeRoute())

    assert aborted == ["blockedbyclient"]
    assert session.blocked_requests[0].reason
    assert "resolution_failed" in session.blocked_requests[0].reason


@pytest.mark.asyncio
async def test_playwright_session_blocks_private_websocket_request(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()
    session = PlaywrightCaptureSession(
        runtime,
        resolver=lambda hostname, port: ["127.0.0.1"] if hostname == "evil.test" else ["93.184.216.34"],
    )
    closed: list[tuple[int | None, str | None]] = []
    connected: list[bool] = []

    class FakeWebSocketRoute:
        url = "ws://evil.test/socket"

        async def close(self, *, code: int | None = None, reason: str | None = None) -> None:
            closed.append((code, reason))

        async def connect_to_server(self) -> None:
            connected.append(True)

    await session._route_web_socket(FakeWebSocketRoute())

    assert closed == [(1008, "Blocked by web capture policy")]
    assert connected == []
    assert session.blocked_requests[0].resource_type == "websocket"
    assert session.blocked_requests[0].reason == "loopback"


@pytest.mark.asyncio
async def test_playwright_session_context_blocks_service_workers_and_routes_websockets(
    webcapture_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = webcapture_settings.webcapture()
    calls: dict[str, object] = {}

    class FakeContext:
        async def route(self, pattern, handler) -> None:
            calls["route_pattern"] = pattern
            calls["route_handler"] = handler

        async def route_web_socket(self, pattern, handler) -> None:
            calls["ws_pattern"] = pattern
            calls["ws_handler"] = handler

        async def new_page(self) -> object:
            page = object()
            calls["page"] = page
            return page

        async def close(self) -> None:
            calls["context_closed"] = True

    class FakeBrowser:
        async def new_context(self, **kwargs) -> FakeContext:
            calls["new_context_kwargs"] = kwargs
            return FakeContext()

        async def close(self) -> None:
            calls["browser_closed"] = True

    class FakeChromium:
        async def connect(self, endpoint: str, timeout: int) -> FakeBrowser:
            calls["endpoint"] = endpoint
            calls["timeout"] = timeout
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self) -> None:
            calls["playwright_stopped"] = True

    class FakeAsyncPlaywrightManager:
        async def start(self) -> FakePlaywright:
            calls["started"] = True
            return FakePlaywright()

    monkeypatch.setattr(
        playwright_async_api,
        "async_playwright",
        lambda: FakeAsyncPlaywrightManager(),
    )

    session = PlaywrightCaptureSession(runtime, resolver=lambda hostname, port: ["93.184.216.34"])

    async with session:
        pass

    assert calls["new_context_kwargs"] == {
        "viewport": {"width": runtime.viewport_width, "height": runtime.viewport_height},
        "service_workers": "block",
    }
    assert calls["route_pattern"] == "**/*"
    assert calls["ws_pattern"] == "**/*"
    assert calls["context_closed"] is True
    assert calls["browser_closed"] is True
    assert calls["playwright_stopped"] is True
