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
