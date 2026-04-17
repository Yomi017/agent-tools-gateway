from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from toolhub.backends.convertx import ConvertXClient
from toolhub.security import PathPolicy, safe_extract_tar_bytes


def _archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        content = b"converted"
        info = tarfile.TarInfo("sample.jpg")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_convertx_client_full_flow(settings) -> None:
    input_file = settings.allowed_input_roots[0] / "sample.png"
    input_file.write_bytes(b"png")
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(
                200,
                text="<html></html>",
                headers=[
                    ("set-cookie", "auth=abc; Path=/"),
                    ("set-cookie", "jobId=42; Path=/"),
                ],
            )
        if request.method == "POST" and request.url.path == "/conversions":
            return httpx.Response(
                200,
                text='<button data-value="jpg,imagemagick" data-target="jpg" data-converter="imagemagick">jpg</button>',
            )
        if request.method == "POST" and request.url.path == "/upload":
            return httpx.Response(200, json={"message": "Files uploaded successfully."})
        if request.method == "POST" and request.url.path == "/convert":
            return httpx.Response(302, headers={"location": "/results/42"})
        if request.method == "POST" and request.url.path == "/progress/42":
            return httpx.Response(200, text='<progress max="1" value="1"></progress>')
        if request.method == "GET" and request.url.path == "/archive/42":
            return httpx.Response(200, content=_archive())
        return httpx.Response(404, text="missing")

    client = ConvertXClient(settings, transport=httpx.MockTransport(handler))
    job_id, archive, duration_ms = await client.convert_files([input_file], output_format="jpg")

    assert job_id == "42"
    assert duration_ms >= 0
    assert "POST /upload" in calls
    output_dir = PathPolicy(settings).validate_output_dir(None)
    outputs = safe_extract_tar_bytes(archive, output_dir, PathPolicy(settings))
    assert outputs[0].filename == "sample.jpg"
