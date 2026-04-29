from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from toolhub.cli import _parse_bool, _parse_timeout, main


def _run_cli(
    argv: list[str],
    *,
    handler,
    monkeypatch: pytest.MonkeyPatch,
    token: str | None = None,
) -> tuple[int, dict[str, Any], list[httpx.Request], list[dict[str, str]]]:
    requests: list[httpx.Request] = []
    header_snapshots: list[dict[str, str]] = []

    if token is None:
        monkeypatch.delenv("TOOLHUB_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TOOLHUB_AUTH_TOKEN", token)

    def wrapped_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def client_factory(api_url: str, timeout: float, headers: dict[str, str]):
        header_snapshots.append(headers)
        return httpx.Client(
            base_url=api_url,
            headers=headers,
            transport=httpx.MockTransport(wrapped_handler),
            timeout=timeout,
        )

    stdout = io.StringIO()
    exit_code = main(argv, client_factory=client_factory, stdout=stdout)
    return exit_code, json.loads(stdout.getvalue()), requests, header_snapshots


def test_parse_bool_accepts_common_values() -> None:
    for value in ["true", "TRUE", "1", "yes", "y", "on"]:
        assert _parse_bool(value) is True
    for value in ["false", "FALSE", "0", "no", "n", "off"]:
        assert _parse_bool(value) is False


def test_parse_timeout_requires_positive_number() -> None:
    assert _parse_timeout("12.5") == 12.5
    with pytest.raises(Exception):
        _parse_timeout("0")
    with pytest.raises(Exception):
        _parse_timeout("soon")


def test_invalid_bool_returns_json_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "sample.png"
    input_path.write_bytes(b"png")
    stdout = io.StringIO()

    exit_code = main(
        [
            "convertx",
            "png",
            str(input_path),
            "jpg",
            str(tmp_path),
            "maybe",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"


def test_input_format_mismatch_fails_before_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.jpg"
    input_path.write_bytes(b"jpg")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "png",
            str(input_path),
            "jpg",
            str(tmp_path),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert requests == []
    assert payload["error"]["code"] == "input_format_mismatch"


def test_unsupported_output_format_returns_available_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.png"
    input_path.write_bytes(b"png")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/convertx/targets"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "convertx",
                "input_format": "png",
                "targets": [{"target": "webp", "converter": "imagemagick", "value": "webp,imagemagick"}],
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "png",
            str(input_path),
            "jpg",
            str(tmp_path),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert [request.url.path for request in requests] == ["/v1/convertx/targets"]
    assert payload["error"]["code"] == "format_not_supported"
    assert payload["error"]["details"]["available"][0]["target"] == "webp"


def test_check_only_lists_targets_without_converting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.png"
    input_path.write_bytes(b"png")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convertx/convert":
            raise AssertionError("convert endpoint should not be called")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "convertx",
                "input_format": "png",
                "targets": [{"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"}],
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "--check",
            "png",
            str(input_path),
            "jpg",
            str(tmp_path / "out"),
            "false",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/convertx/targets"]
    assert payload["check"] is True
    assert payload["selected_target"]["target"] == "jpg"


def test_successful_convert_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.png"
    input_path.write_bytes(b"png")
    output_dir = tmp_path / "output"
    posted_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convertx/targets":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "backend": "convertx",
                    "input_format": "png",
                    "targets": [
                        {"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"}
                    ],
                },
            )
        if request.url.path == "/v1/convertx/convert":
            posted_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "backend": "convertx",
                    "job_id": "42",
                    "outputs": [{"path": str(output_dir / "sample.jpg"), "filename": "sample.jpg"}],
                    "duration_ms": 12,
                },
            )
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "png",
            str(input_path),
            "jpg",
            str(output_dir),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == [
        "/v1/convertx/targets",
        "/v1/convertx/convert",
    ]
    assert posted_payloads == [
        {
            "input_path": str(input_path.resolve()),
            "output_format": "jpg",
            "output_dir": str(output_dir.resolve(strict=False)),
            "overwrite": True,
        }
    ]
    assert payload["job_id"] == "42"


def test_directory_batch_check_only_lists_matching_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "batch"
    input_dir.mkdir()
    (input_dir / "a.webp").write_bytes(b"a")
    (input_dir / "b.webp").write_bytes(b"b")
    (input_dir / "ignore.png").write_bytes(b"png")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convertx/convert-batch":
            raise AssertionError("convert-batch endpoint should not be called")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "convertx",
                "input_format": "webp",
                "targets": [{"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"}],
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "--check",
            "webp",
            str(input_dir),
            "jpg",
            str(tmp_path / "out"),
            "false",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/convertx/targets"]
    assert payload["mode"] == "directory"
    assert payload["input_count"] == 2
    assert payload["input_paths"] == [
        str((input_dir / "a.webp").resolve()),
        str((input_dir / "b.webp").resolve()),
    ]


def test_directory_batch_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "batch"
    input_dir.mkdir()
    (input_dir / "a.webp").write_bytes(b"a")
    (input_dir / "b.webp").write_bytes(b"b")
    output_dir = tmp_path / "output"
    posted_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convertx/targets":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "backend": "convertx",
                    "input_format": "webp",
                    "targets": [{"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"}],
                },
            )
        if request.url.path == "/v1/convertx/convert-batch":
            posted_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "backend": "convertx",
                    "job_id": "43",
                    "outputs": [
                        {"path": str(output_dir / "a.jpg"), "filename": "a.jpg"},
                        {"path": str(output_dir / "b.jpg"), "filename": "b.jpg"},
                    ],
                    "duration_ms": 34,
                },
            )
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "webp",
            str(input_dir),
            "jpg",
            str(output_dir),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == [
        "/v1/convertx/targets",
        "/v1/convertx/convert-batch",
    ]
    assert posted_payloads == [
        {
            "input_paths": [
                str((input_dir / "a.webp").resolve()),
                str((input_dir / "b.webp").resolve()),
            ],
            "output_format": "jpg",
            "output_dir": str(output_dir.resolve(strict=False)),
            "overwrite": True,
        }
    ]
    assert payload["job_id"] == "43"


def test_directory_without_matching_files_fails_before_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "batch"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"a")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "convertx",
            "webp",
            str(input_dir),
            "jpg",
            str(tmp_path / "out"),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert requests == []
    assert payload["error"]["code"] == "input_dir_empty"


def test_auth_token_is_sent_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.png"
    input_path.write_bytes(b"png")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "convertx",
                "input_format": "png",
                "targets": [{"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"}],
            },
        )

    exit_code, _payload, _requests, headers = _run_cli(
        [
            "convertx",
            "--check",
            "png",
            str(input_path),
            "jpg",
            str(tmp_path),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
        token="secret-token",
    )

    assert exit_code == 0
    assert headers == [{"Authorization": "Bearer secret-token"}]


def test_webcapture_invalid_url_fails_before_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "webcapture",
            "notaurl",
            "pdf",
            str(tmp_path),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert requests == []
    assert payload["error"]["code"] == "invalid_url"


def test_webcapture_invalid_output_format_is_argument_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()

    exit_code = main(
        [
            "webcapture",
            "https://example.com",
            "docx",
            str(tmp_path),
            "true",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"


def test_webcapture_check_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/webcapture/check"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "webcapture",
                "check": True,
                "normalized_url": "https://example.com/",
                "planned_output_path": str(output_dir / "example-home.pdf"),
                "effective_options": {
                    "output_format": "pdf",
                    "wait_until": "networkidle",
                },
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "webcapture",
            "--check",
            "--name",
            "example-home",
            "https://example.com",
            "pdf",
            str(output_dir),
            "false",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/webcapture/check"]
    assert json.loads(requests[0].content) == {
        "url": "https://example.com",
        "output_format": "pdf",
        "output_dir": str(output_dir.resolve(strict=False)),
        "overwrite": False,
        "filename_stem": "example-home",
    }
    assert payload["check"] is True
    assert payload["normalized_url"] == "https://example.com/"


def test_webcapture_capture_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/webcapture/capture"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "webcapture",
                "requested_url": "https://example.com",
                "final_url": "https://example.com/",
                "title": "Example Domain",
                "output": {
                    "path": str(output_dir / "example-home.png"),
                    "filename": "example-home.png",
                },
                "duration_ms": 12,
                "navigation_status": {"status": 200, "ok": True, "url": "https://example.com/"},
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "webcapture",
            "--name",
            "example-home",
            "--wait-until",
            "load",
            "--full-page",
            "false",
            "https://example.com",
            "png",
            str(output_dir),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/webcapture/capture"]
    assert json.loads(requests[0].content) == {
        "url": "https://example.com",
        "output_format": "png",
        "output_dir": str(output_dir.resolve(strict=False)),
        "overwrite": True,
        "filename_stem": "example-home",
        "wait_until": "load",
        "full_page": False,
    }
    assert payload["output"]["filename"] == "example-home.png"


def test_docling_missing_input_fails_before_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "docling",
            str(tmp_path / "missing.pdf"),
            "md",
            str(tmp_path / "output"),
            "false",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert requests == []
    assert payload["error"]["code"] == "input_not_found"


def test_docling_check_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")
    output_dir = tmp_path / "output"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/docling/check"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "docling",
                "check": True,
                "input_path": str(input_path.resolve()),
                "planned_output_path": str(output_dir / "lecture.md"),
                "effective_options": {
                    "output_format": "md",
                    "do_ocr": True,
                    "table_mode": "accurate",
                },
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "docling",
            "--check",
            "--name",
            "lecture",
            "--do-ocr",
            "true",
            "--table-mode",
            "accurate",
            str(input_path),
            "md",
            str(output_dir),
            "false",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/docling/check"]
    assert json.loads(requests[0].content) == {
        "input_path": str(input_path.resolve()),
        "output_format": "md",
        "output_dir": str(output_dir.resolve(strict=False)),
        "overwrite": False,
        "filename_stem": "lecture",
        "do_ocr": True,
        "table_mode": "accurate",
    }
    assert payload["planned_output_path"].endswith("/lecture.md")


def test_docling_convert_posts_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "sample.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")
    output_dir = tmp_path / "output"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/docling/convert"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "docling",
                "input_path": str(input_path.resolve()),
                "output_format": "html",
                "task_id": "task-123",
                "output": {
                    "path": str(output_dir / "lecture.html"),
                    "filename": "lecture.html",
                },
                "duration_ms": 21,
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "docling",
            "--name",
            "lecture",
            "--include-images",
            "true",
            "--pdf-backend",
            "dlparse_v4",
            str(input_path),
            "html",
            str(output_dir),
            "true",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/docling/convert"]
    assert json.loads(requests[0].content) == {
        "input_path": str(input_path.resolve()),
        "output_format": "html",
        "output_dir": str(output_dir.resolve(strict=False)),
        "overwrite": True,
        "filename_stem": "lecture",
        "pdf_backend": "dlparse_v4",
        "include_images": True,
    }
    assert payload["task_id"] == "task-123"


def test_searxng_empty_query_fails_before_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    exit_code, payload, requests, _headers = _run_cli(
        [
            "searxng",
            "   ",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 1
    assert requests == []
    assert payload["error"]["code"] == "invalid_query"


def test_searxng_search_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/searxng/search"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "backend": "searxng",
                "query": "openai gpt-5.5",
                "result_count": 1,
                "results": [
                    {
                        "title": "OpenAI launches GPT-5.5",
                        "url": "https://example.com/gpt-5-5",
                        "snippet": "Launch details",
                        "engine": "brave",
                        "position": 1,
                    }
                ],
                "effective_options": {
                    "limit": 3,
                    "language": "zh-CN",
                    "safe_search": "moderate",
                    "page": 2,
                    "time_range": "day",
                },
                "warnings": {"unresponsive_engines": ["duckduckgo: timeout"]},
                "duration_ms": 18,
            },
        )

    exit_code, payload, requests, _headers = _run_cli(
        [
            "searxng",
            "--limit",
            "3",
            "--language",
            "zh-CN",
            "--time-range",
            "day",
            "--safe-search",
            "moderate",
            "--page",
            "2",
            "openai gpt-5.5",
        ],
        handler=handler,
        monkeypatch=monkeypatch,
    )

    assert exit_code == 0
    assert [request.url.path for request in requests] == ["/v1/searxng/search"]
    assert json.loads(requests[0].content) == {
        "query": "openai gpt-5.5",
        "limit": 3,
        "language": "zh-CN",
        "time_range": "day",
        "safe_search": "moderate",
        "page": 2,
    }
    assert payload["result_count"] == 1
    assert payload["results"][0]["engine"] == "brave"
