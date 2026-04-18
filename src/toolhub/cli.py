from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

from .tools.convertx.client import normalize_format
from .tools.webcapture.models import normalize_capture_format, normalize_wait_until


DEFAULT_API_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT_SECONDS = 660.0

JsonObject = dict[str, Any]
ClientFactory = Callable[[str, float, dict[str, str]], AbstractContextManager[httpx.Client]]


@dataclass(frozen=True)
class CliError(Exception):
    code: str
    message: str
    details: JsonObject | None = None
    exit_code: int = 1

    def to_payload(self) -> JsonObject:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details or {},
            },
        }


@dataclass(frozen=True)
class CommandContext:
    client_factory: ClientFactory


@dataclass(frozen=True)
class InputSelection:
    source_kind: str
    paths: list[Path]


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError(
            "invalid_arguments",
            message,
            details={"usage": self.format_usage().strip()},
            exit_code=2,
        )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    truthy = {"1", "true", "t", "yes", "y", "on"}
    falsey = {"0", "false", "f", "no", "n", "off"}
    if normalized in truthy:
        return True
    if normalized in falsey:
        return False
    raise argparse.ArgumentTypeError(
        "overwrite must be one of true/false/1/0/yes/no/on/off"
    )


def _parse_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number of seconds") from exc
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than 0")
    return timeout


def _parse_capture_output_format(value: str) -> str:
    try:
        return normalize_capture_format(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_wait_until(value: str) -> str:
    try:
        return normalize_wait_until(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _print_json(payload: JsonObject, stdout: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)


def _default_client_factory(
    api_url: str,
    timeout_seconds: float,
    headers: dict[str, str],
) -> AbstractContextManager[httpx.Client]:
    return httpx.Client(
        base_url=api_url.rstrip("/"),
        headers=headers,
        timeout=httpx.Timeout(timeout_seconds),
    )


def _auth_headers() -> dict[str, str]:
    token = os.getenv("TOOLHUB_AUTH_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _validate_input_file(path: Path, input_format: str, *, source_path: str) -> Path:
    if not path.is_file():
        raise CliError(
            "input_not_file",
            f"Input path is not a regular file: {source_path}",
            details={"path": str(path)},
        )

    actual_format = normalize_format(path.suffix)
    if actual_format != input_format:
        raise CliError(
            "input_format_mismatch",
            f"Input file extension is {actual_format}, not {input_format}.",
            details={
                "path": str(path),
                "input_format": input_format,
                "actual_format": actual_format,
            },
        )
    return path


def _resolve_input_selection(raw_path: str, input_format: str) -> InputSelection:
    path = Path(raw_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise CliError(
            "input_not_found",
            f"Input path does not exist: {raw_path}",
            details={"path": raw_path},
        ) from exc

    if resolved.is_file():
        return InputSelection(
            source_kind="file",
            paths=[_validate_input_file(resolved, input_format, source_path=raw_path)],
        )

    if not resolved.is_dir():
        raise CliError(
            "input_not_file_or_dir",
            f"Input path is neither a regular file nor a directory: {raw_path}",
            details={"path": str(resolved)},
        )

    files = sorted(
        child.resolve(strict=True)
        for child in resolved.iterdir()
        if child.is_file() and normalize_format(child.suffix) == input_format
    )
    if not files:
        raise CliError(
            "input_dir_empty",
            f"No .{input_format} files were found in directory: {raw_path}",
            details={"path": str(resolved), "input_format": input_format},
        )

    duplicates = sorted(name for name, count in Counter(path.name for path in files).items() if count > 1)
    if duplicates:
        raise CliError(
            "duplicate_input_filenames",
            "Batch conversion requires unique filenames within the input directory.",
            details={"path": str(resolved), "duplicate_filenames": duplicates},
        )

    return InputSelection(source_kind="directory", paths=files)


def _resolve_output_dir(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise CliError(
            "output_not_dir",
            f"Output path exists but is not a directory: {raw_path}",
            details={"path": str(resolved)},
        )
    return resolved


def _resolve_capture_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if not normalized:
        raise CliError("invalid_url", "URL is required.", details={"url": raw_url})
    parts = urlsplit(normalized)
    try:
        _port = parts.port
    except ValueError as exc:
        raise CliError(
            "invalid_url",
            "URL contains an invalid port.",
            details={"url": raw_url},
        ) from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise CliError(
            "invalid_url",
            "URL must use http or https and include a hostname.",
            details={"url": raw_url},
        )
    return normalized


def _response_json(response: httpx.Response, action: str) -> JsonObject:
    if response.status_code >= 400:
        raise CliError(
            "api_error",
            f"Toolhub failed to {action}.",
            details={
                "status_code": response.status_code,
                "body_preview": response.text[:500],
            },
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise CliError(
            "api_error",
            f"Toolhub returned non-JSON while trying to {action}.",
            details={
                "status_code": response.status_code,
                "body_preview": response.text[:500],
            },
        ) from exc

    if not isinstance(payload, dict):
        raise CliError(
            "api_error",
            f"Toolhub returned an unexpected JSON payload while trying to {action}.",
            details={"payload_type": type(payload).__name__},
        )

    if payload.get("ok") is False:
        error = payload.get("error")
        if isinstance(error, dict):
            raise CliError(
                str(error.get("code") or "toolhub_error"),
                str(error.get("message") or "Toolhub returned an error."),
                details=error.get("details") if isinstance(error.get("details"), dict) else {},
            )
        raise CliError("toolhub_error", "Toolhub returned an error.", details=payload)

    return payload


def _target_matches(
    target: Any,
    *,
    output_format: str,
    converter: str | None,
) -> bool:
    if not isinstance(target, dict):
        return False
    if normalize_format(str(target.get("target") or "")) != output_format:
        return False
    if converter is None:
        return True
    return str(target.get("converter") or "").lower() == converter.lower()


def _select_target(
    payload: JsonObject,
    *,
    input_format: str,
    output_format: str,
    converter: str | None,
) -> JsonObject:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise CliError(
            "api_error",
            "Toolhub targets response did not include a targets list.",
            details={"payload": payload},
        )

    for target in targets:
        if _target_matches(target, output_format=output_format, converter=converter):
            return target

    available = [target for target in targets if isinstance(target, dict)]
    raise CliError(
        "format_not_supported",
        f"ConvertX does not list a conversion from {input_format} to {output_format}.",
        details={
            "input_format": input_format,
            "output_format": output_format,
            "converter": converter,
            "available": available,
        },
    )


def _run_convertx(args: argparse.Namespace, context: CommandContext) -> JsonObject:
    input_format = normalize_format(args.input_format)
    output_format = normalize_format(args.output_format)
    selection = _resolve_input_selection(args.input_path, input_format)
    output_dir = _resolve_output_dir(args.output_dir)

    with context.client_factory(args.api_url, args.timeout, _auth_headers()) as client:
        targets_response = client.get(
            "/v1/convertx/targets",
            params={"input_format": input_format},
        )
        targets_payload = _response_json(targets_response, "list ConvertX targets")
        selected = _select_target(
            targets_payload,
            input_format=input_format,
            output_format=output_format,
            converter=args.converter,
        )

        if args.check:
            payload: JsonObject = {
                "ok": True,
                "backend": "convertx",
                "check": True,
                "mode": selection.source_kind,
                "input_format": input_format,
                "output_format": output_format,
                "output_dir": str(output_dir),
                "overwrite": args.overwrite,
                "converter": args.converter,
                "input_count": len(selection.paths),
                "selected_target": selected,
            }
            if selection.source_kind == "file":
                payload["input_path"] = str(selection.paths[0])
            else:
                payload["input_paths"] = [str(path) for path in selection.paths]
            return payload

        if selection.source_kind == "file":
            request_payload: JsonObject = {
                "input_path": str(selection.paths[0]),
                "output_format": output_format,
                "output_dir": str(output_dir),
                "overwrite": args.overwrite,
            }
            if args.converter:
                request_payload["converter"] = args.converter

            convert_response = client.post("/v1/convertx/convert", json=request_payload)
            return _response_json(convert_response, "convert file")

        request_payload = {
            "input_paths": [str(path) for path in selection.paths],
            "output_format": output_format,
            "output_dir": str(output_dir),
            "overwrite": args.overwrite,
        }
        if args.converter:
            request_payload["converter"] = args.converter

        convert_response = client.post("/v1/convertx/convert-batch", json=request_payload)
        return _response_json(convert_response, "convert batch")


def _run_webcapture(args: argparse.Namespace, context: CommandContext) -> JsonObject:
    request_payload: JsonObject = {
        "url": _resolve_capture_url(args.url),
        "output_format": args.output_format,
        "output_dir": str(_resolve_output_dir(args.output_dir)),
        "overwrite": args.overwrite,
    }
    if args.name:
        request_payload["filename_stem"] = args.name
    if args.wait_until:
        request_payload["wait_until"] = args.wait_until
    if args.full_page is not None:
        request_payload["full_page"] = args.full_page

    endpoint = "/v1/webcapture/check" if args.check else "/v1/webcapture/capture"
    action = "validate webcapture request" if args.check else "capture webpage"

    with context.client_factory(args.api_url, args.timeout, _auth_headers()) as client:
        response = client.post(endpoint, json=request_payload)
        return _response_json(response, action)


def _add_convertx_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "convertx",
        help="Convert one file or one flat directory of matching files through the local ConvertX gateway.",
    )
    parser.add_argument("input_format")
    parser.add_argument("input_path")
    parser.add_argument("output_format")
    parser.add_argument("output_dir")
    parser.add_argument("overwrite", type=_parse_bool)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate path and format support without converting.",
    )
    parser.add_argument(
        "--converter",
        help="Require a specific ConvertX converter.",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("TOOLHUB_API_URL", DEFAULT_API_URL),
        help=f"Toolhub REST API URL. Defaults to TOOLHUB_API_URL or {DEFAULT_API_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=_parse_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS:g}.",
    )
    parser.set_defaults(handler=_run_convertx)


def _add_webcapture_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "webcapture",
        help="Capture one webpage into pdf, png, or markdown through the local webcapture backend.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate URL and output planning without capturing.",
    )
    parser.add_argument(
        "--name",
        help="Optional output filename stem without extension.",
    )
    parser.add_argument(
        "--wait-until",
        type=_parse_wait_until,
        help="Navigation readiness event for the page load.",
    )
    parser.add_argument(
        "--full-page",
        type=_parse_bool,
        help="Whether png screenshots should capture the full scrollable page.",
    )
    parser.add_argument("url")
    parser.add_argument("output_format", type=_parse_capture_output_format)
    parser.add_argument("output_dir")
    parser.add_argument("overwrite", type=_parse_bool)
    parser.add_argument(
        "--api-url",
        default=os.getenv("TOOLHUB_API_URL", DEFAULT_API_URL),
        help=f"Toolhub REST API URL. Defaults to TOOLHUB_API_URL or {DEFAULT_API_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=_parse_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS:g}.",
    )
    parser.set_defaults(handler=_run_webcapture)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="tool-call",
        description="Small JSON-first CLI for agent-callable local tools.",
    )
    subparsers = parser.add_subparsers(dest="tool", required=True)
    _add_convertx_parser(subparsers)
    _add_webcapture_parser(subparsers)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    stdout: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    parser = build_parser()
    context = CommandContext(client_factory=client_factory or _default_client_factory)

    try:
        args = parser.parse_args(argv)
        handler = getattr(args, "handler")
        payload = handler(args, context)
    except CliError as exc:
        _print_json(exc.to_payload(), out)
        return exc.exit_code
    except httpx.RequestError as exc:
        payload = CliError(
            "api_unreachable",
            "Could not reach Toolhub API.",
            details={"error": str(exc)},
        ).to_payload()
        _print_json(payload, out)
        return 1
    except Exception as exc:
        payload = CliError(
            "internal_error",
            "Unexpected tool-call failure.",
            details={"type": type(exc).__name__, "message": str(exc)},
        ).to_payload()
        _print_json(payload, out)
        return 1

    _print_json(payload, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
