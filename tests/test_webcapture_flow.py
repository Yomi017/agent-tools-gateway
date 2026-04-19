from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient

from toolhub.api import create_app
from toolhub.backends.webcapture import WebCaptureClient
from toolhub.config import Settings
from toolhub.errors import CaptureLimitError, OutputExistsError
from toolhub.security import CheckedUrl
from toolhub.tools.webcapture.backend import capture_url
from toolhub.tools.webcapture.client import CaptureArtifact, PlaywrightCaptureSession, _render_markdown


@dataclass
class FakeSession:
    calls: list[dict[str, object]]
    artifact_by_format: dict[str, CaptureArtifact]

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def capture(
        self,
        *,
        url: str,
        output_format: str,
        wait_until: str | None = None,
        full_page: bool | None = None,
    ) -> CaptureArtifact:
        self.calls.append(
            {
                "url": url,
                "output_format": output_format,
                "wait_until": wait_until,
                "full_page": full_page,
            }
        )
        return self.artifact_by_format[output_format]


def _session_factory(
    calls: list[dict[str, object]],
    artifact_by_format: dict[str, CaptureArtifact],
):
    def factory(_settings, _resolver):
        return FakeSession(calls=calls, artifact_by_format=artifact_by_format)

    return factory


@dataclass
class FakeNavigationResponse:
    status: int = 200
    ok: bool = True
    url: str = "https://example.com/final"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_format", "full_page", "expected_content"),
    [
        ("pdf", None, b"%PDF-1.7"),
        ("png", False, b"\x89PNG\r\n"),
        ("md", None, b"# Example Domain\n"),
    ],
)
async def test_webcapture_client_capture_uses_session_factory(
    webcapture_settings,
    output_format: str,
    full_page: bool | None,
    expected_content: bytes,
) -> None:
    runtime = webcapture_settings.webcapture()
    calls: list[dict[str, object]] = []
    client = WebCaptureClient(
        runtime,
        session_factory=_session_factory(
            calls,
            {
                output_format: CaptureArtifact(
                    content=expected_content,
                    final_url="https://example.com/final",
                    title="Example Domain",
                    navigation_status={"status": 200, "ok": True, "url": "https://example.com/final"},
                )
            },
        ),
    )

    artifact, duration_ms = await client.capture(
        url="https://example.com",
        output_format=output_format,
        wait_until="load",
        full_page=full_page,
    )

    assert artifact.content == expected_content
    assert artifact.final_url == "https://example.com/final"
    assert duration_ms >= 0
    assert calls == [
        {
            "url": "https://example.com",
            "output_format": output_format,
            "wait_until": "load",
            "full_page": full_page,
        }
    ]


@pytest.mark.asyncio
async def test_webcapture_health_reads_pressure_payload(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pressure"
        assert request.url.params["token"] == runtime.token
        return httpx.Response(
            200,
            json={"isAvailable": True, "running": 0, "queued": 0},
        )

    client = WebCaptureClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert payload["reachable"] is True
    assert payload["isAvailable"] is True
    assert payload["running"] == 0
    assert payload["queued"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_webcapture_health_marks_auth_failure_unreachable(
    webcapture_settings,
    status_code: int,
) -> None:
    runtime = webcapture_settings.webcapture()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pressure"
        assert request.url.params["token"] == runtime.token
        return httpx.Response(status_code, text="Unauthorized")

    client = WebCaptureClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert payload["reachable"] is False
    assert payload["status_code"] == status_code
    assert payload["body_preview"] == "Unauthorized"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_format", "content"),
    [
        ("pdf", b"%PDF-1.7 fake"),
        ("png", b"\x89PNG\r\nfake"),
        ("md", b"# Example Domain\n"),
    ],
)
async def test_backend_capture_url_writes_output_file(
    webcapture_settings,
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
    content: bytes,
) -> None:
    class FakeClient:
        def __init__(self, _runtime) -> None:
            pass

        async def capture(self, **kwargs):
            assert kwargs["output_format"] == output_format
            return (
                CaptureArtifact(
                    content=content,
                    final_url="https://example.com/final",
                    title="Example Domain",
                    navigation_status={"status": 200, "ok": True, "url": "https://example.com/final"},
                ),
                17,
            )

    monkeypatch.setattr("toolhub.tools.webcapture.backend.WebCaptureClient", FakeClient)
    monkeypatch.setattr(
        "toolhub.tools.webcapture.backend.validate_web_url",
        lambda url, block_private_networks=True: CheckedUrl(
            raw_url=url,
            normalized_url=url,
            hostname="example.com",
            port=443,
        ),
    )

    output_dir = webcapture_settings.webcapture().allowed_output_roots[0]
    payload = await capture_url(
        url="https://example.com",
        output_format=output_format,
        output_dir=str(output_dir),
        filename_stem="example-home",
        overwrite=True,
        settings=webcapture_settings,
    )

    assert payload.output.filename == f"example-home.{output_format}"
    assert payload.duration_ms == 17
    output_path = output_dir.joinpath(f"example-home.{output_format}")
    assert output_path.read_bytes() == content
    assert output_path.stat().st_mode & 0o777 == 0o644


def test_render_markdown_falls_back_to_body_when_readability_is_too_short() -> None:
    markdown = _render_markdown(
        html="<html><body><p>Short fallback body.</p></body></html>",
        source_url="https://example.com",
        title="Example Domain",
    )

    assert "Source URL: https://example.com" in markdown
    assert "Captured At:" in markdown
    assert "Short fallback body." in markdown


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://example.com", "output_format": 123},
        {"url": "https://example.com", "output_format": "pdf", "wait_until": 123},
    ],
)
def test_webcapture_invalid_payload_types_return_422(payload) -> None:
    app = create_app(Settings(backends={"webcapture": {"enabled": True}}))
    client = TestClient(app)

    response = client.post("/v1/webcapture/check", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_playwright_capture_rejects_full_page_height_limit(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture().model_copy(update={"max_full_page_height_px": 1000})
    session = PlaywrightCaptureSession(runtime, resolver=lambda hostname, port: ["93.184.216.34"])

    class FakePage:
        url = "https://example.com/final"

        async def goto(self, *args, **kwargs) -> FakeNavigationResponse:
            return FakeNavigationResponse()

        async def wait_for_timeout(self, _delay_ms: int) -> None:
            return None

        async def title(self) -> str:
            return "Example Domain"

        async def evaluate(self, _script: str) -> int:
            return 1001

        async def screenshot(self, **kwargs) -> bytes:
            raise AssertionError("screenshot should not run when the page height exceeds the limit")

    session._page = FakePage()

    with pytest.raises(CaptureLimitError) as exc_info:
        await session.capture(url="https://example.com", output_format="png", full_page=True)

    assert exc_info.value.details == {
        "output_format": "png",
        "limit": 1000,
        "actual": 1001,
        "page_height_px": 1001,
    }


@pytest.mark.asyncio
async def test_playwright_capture_rejects_oversized_artifact(webcapture_settings) -> None:
    runtime = webcapture_settings.webcapture().model_copy(update={"max_capture_bytes": 8})
    session = PlaywrightCaptureSession(runtime, resolver=lambda hostname, port: ["93.184.216.34"])

    class FakePage:
        url = "https://example.com/final"

        async def goto(self, *args, **kwargs) -> FakeNavigationResponse:
            return FakeNavigationResponse()

        async def wait_for_timeout(self, _delay_ms: int) -> None:
            return None

        async def title(self) -> str:
            return "Example Domain"

        async def pdf(self, **kwargs) -> bytes:
            return b"%PDF-1.7 TOO LARGE"

    session._page = FakePage()

    with pytest.raises(CaptureLimitError) as exc_info:
        await session.capture(url="https://example.com", output_format="pdf")

    assert exc_info.value.details == {
        "output_format": "pdf",
        "limit": 8,
        "actual": len(b"%PDF-1.7 TOO LARGE"),
    }


@pytest.mark.asyncio
async def test_backend_capture_url_rejects_symlink_race_without_overwrite(
    webcapture_settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    output_dir = webcapture_settings.webcapture().allowed_output_roots[0]
    output_path = output_dir / "example-race.pdf"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")

    class FakeClient:
        def __init__(self, _runtime) -> None:
            pass

        async def capture(self, **kwargs):
            try:
                output_path.symlink_to(outside)
            except OSError:
                pytest.skip("symlinks are not supported on this filesystem")
            return (
                CaptureArtifact(
                    content=b"%PDF-1.7 new",
                    final_url="https://example.com/final",
                    title="Example Domain",
                    navigation_status={"status": 200, "ok": True, "url": "https://example.com/final"},
                ),
                17,
            )

    monkeypatch.setattr("toolhub.tools.webcapture.backend.WebCaptureClient", FakeClient)
    monkeypatch.setattr(
        "toolhub.tools.webcapture.backend.validate_web_url",
        lambda url, block_private_networks=True: CheckedUrl(
            raw_url=url,
            normalized_url=url,
            hostname="example.com",
            port=443,
        ),
    )

    with pytest.raises(OutputExistsError):
        await capture_url(
            url="https://example.com",
            output_format="pdf",
            output_dir=str(output_dir),
            filename_stem="example-race",
            overwrite=False,
            settings=webcapture_settings,
        )

    assert output_path.is_symlink()
    assert outside.read_bytes() == b"outside"


@pytest.mark.asyncio
async def test_backend_capture_url_overwrite_replaces_symlink_without_touching_outside(
    webcapture_settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    output_dir = webcapture_settings.webcapture().allowed_output_roots[0]
    output_path = output_dir / "example-race.pdf"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")

    class FakeClient:
        def __init__(self, _runtime) -> None:
            pass

        async def capture(self, **kwargs):
            try:
                output_path.symlink_to(outside)
            except OSError:
                pytest.skip("symlinks are not supported on this filesystem")
            return (
                CaptureArtifact(
                    content=b"%PDF-1.7 replaced",
                    final_url="https://example.com/final",
                    title="Example Domain",
                    navigation_status={"status": 200, "ok": True, "url": "https://example.com/final"},
                ),
                17,
            )

    monkeypatch.setattr("toolhub.tools.webcapture.backend.WebCaptureClient", FakeClient)
    monkeypatch.setattr(
        "toolhub.tools.webcapture.backend.validate_web_url",
        lambda url, block_private_networks=True: CheckedUrl(
            raw_url=url,
            normalized_url=url,
            hostname="example.com",
            port=443,
        ),
    )

    payload = await capture_url(
        url="https://example.com",
        output_format="pdf",
        output_dir=str(output_dir),
        filename_stem="example-race",
        overwrite=True,
        settings=webcapture_settings,
    )

    assert payload.output.path == str(output_path)
    assert output_path.is_symlink() is False
    assert output_path.read_bytes() == b"%PDF-1.7 replaced"
    assert outside.read_bytes() == b"outside"
