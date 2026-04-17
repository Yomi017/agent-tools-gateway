from __future__ import annotations

from pathlib import Path
from typing import Any

from .backends.convertx import ConvertXClient, normalize_format
from .config import Settings, get_settings
from .errors import ToolhubError, UpstreamError
from .models import ConvertSuccess, HealthResponse, TargetsSuccess
from .security import PathPolicy, safe_extract_tar_bytes


def error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ToolhubError):
        return exc.to_payload()
    return ToolhubError(
        "Unexpected toolhub failure.",
        code="internal_error",
        details={"type": type(exc).__name__, "message": str(exc)},
    ).to_payload()


def _settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


async def health(settings: Settings | None = None) -> HealthResponse:
    runtime = _settings(settings)
    client = ConvertXClient(runtime)
    convertx = await client.health()
    return HealthResponse(backends={"convertx": convertx})


async def list_conversion_targets(
    input_format: str | None = None,
    *,
    settings: Settings | None = None,
) -> TargetsSuccess:
    runtime = _settings(settings)
    client = ConvertXClient(runtime)
    normalized = normalize_format(input_format) if input_format else None
    targets = await client.list_targets(normalized)
    return TargetsSuccess(input_format=normalized, targets=targets)


async def convert_file(
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
    *,
    settings: Settings | None = None,
) -> ConvertSuccess:
    return await convert_batch(
        [input_path],
        output_format=output_format,
        output_dir=output_dir,
        converter=converter,
        overwrite=overwrite,
        settings=settings,
    )


async def convert_batch(
    input_paths: list[str],
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
    *,
    settings: Settings | None = None,
) -> ConvertSuccess:
    runtime = _settings(settings)
    policy = PathPolicy(runtime)
    files = [policy.validate_input_file(path) for path in input_paths]
    out_dir = policy.validate_output_dir(output_dir)

    client = ConvertXClient(runtime)
    job_id, archive, duration_ms = await client.convert_files(
        files,
        output_format=output_format,
        converter=converter,
    )
    outputs = safe_extract_tar_bytes(archive, out_dir, policy, overwrite=overwrite)
    if not outputs:
        raise UpstreamError(
            "ConvertX completed but produced no downloadable files.",
            details={"job_id": job_id, "input_paths": [str(Path(p)) for p in input_paths]},
        )
    return ConvertSuccess(job_id=job_id, outputs=outputs, duration_ms=duration_ms)


async def convert_file_payload(**kwargs: Any) -> dict[str, Any]:
    try:
        return (await convert_file(**kwargs)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def convert_batch_payload(**kwargs: Any) -> dict[str, Any]:
    try:
        return (await convert_batch(**kwargs)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def list_targets_payload(input_format: str | None = None) -> dict[str, Any]:
    try:
        return (await list_conversion_targets(input_format)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def health_payload() -> dict[str, Any]:
    try:
        return (await health()).model_dump()
    except Exception as exc:
        return error_payload(exc)
