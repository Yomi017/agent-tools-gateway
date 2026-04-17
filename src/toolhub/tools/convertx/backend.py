from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from ...config import ConvertXRuntimeSettings, Settings, get_settings
from ...errors import UpstreamError, error_payload
from ...security import PathPolicy, safe_extract_tar_bytes
from .client import ConvertXClient, normalize_format
from .models import (
    BatchConvertRequest,
    ConvertRequest,
    ConvertSuccess,
    TargetsSuccess,
)


backend_key = "convertx"


def _runtime(settings: Settings | None = None) -> ConvertXRuntimeSettings:
    return (settings or get_settings()).convertx()


async def health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = _runtime(settings)
    client = ConvertXClient(runtime)
    return await client.health()


async def list_targets(
    input_format: str | None = None,
    *,
    settings: Settings | None = None,
) -> TargetsSuccess:
    runtime = _runtime(settings)
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
    runtime = _runtime(settings)
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


async def health_payload(settings: Settings | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "backend": backend_key, "health": await health(settings)}
    except Exception as exc:
        return error_payload(exc)


async def list_targets_payload(
    input_format: str | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (await list_targets(input_format, settings=settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def convert_file_payload(
    *,
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await convert_file(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def convert_batch_payload(
    *,
    input_paths: list[str],
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await convert_batch(
                input_paths=input_paths,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


class ConvertXBackend:
    key = backend_key

    def is_enabled(self, settings: Settings) -> bool:
        return settings.convertx().enabled

    async def health(self, settings: Settings) -> dict[str, Any]:
        return await health(settings)

    def register_api(
        self,
        app: FastAPI,
        auth_dependency: Callable[..., None],
        json_response: Callable[[object], JSONResponse],
        settings: Settings,
    ) -> None:
        router = APIRouter(prefix="/v1/convertx", tags=["convertx"])

        @router.get("/targets")
        async def targets_route(
            input_format: str | None = None,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(await list_targets_payload(input_format, settings=settings))

        @router.post("/convert")
        async def convert_route(
            request: ConvertRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await convert_file_payload(
                    input_path=request.input_path,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    converter=request.converter,
                    overwrite=request.overwrite,
                    settings=settings,
                )
            )

        @router.post("/convert-batch")
        async def convert_batch_route(
            request: BatchConvertRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await convert_batch_payload(
                    input_paths=request.input_paths,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    converter=request.converter,
                    overwrite=request.overwrite,
                    settings=settings,
                )
            )

        app.include_router(router)

    def register_mcp(self, mcp: FastMCP, settings: Settings) -> None:
        @mcp.tool(name="convertx_health")
        async def convertx_health() -> dict[str, Any]:
            """Check ConvertX backend reachability."""
            return await health_payload(settings)

        @mcp.tool(name="convertx_list_targets")
        async def convertx_list_targets(input_format: str | None = None) -> dict[str, Any]:
            """List ConvertX output formats, optionally filtered by input extension."""
            return await list_targets_payload(input_format, settings=settings)

        @mcp.tool(name="convertx_convert_file")
        async def convertx_convert_file(
            input_path: str,
            output_format: str,
            output_dir: str | None = None,
            converter: str | None = None,
            overwrite: bool = False,
        ) -> dict[str, Any]:
            """Convert one local file through ConvertX."""
            return await convert_file_payload(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )

        @mcp.tool(name="convertx_convert_batch")
        async def convertx_convert_batch(
            input_paths: list[str],
            output_format: str,
            output_dir: str | None = None,
            converter: str | None = None,
            overwrite: bool = False,
        ) -> dict[str, Any]:
            """Convert multiple local files with the same extension through ConvertX."""
            return await convert_batch_payload(
                input_paths=input_paths,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )

        @mcp.tool(name="list_conversion_targets")
        async def legacy_list_conversion_targets(
            input_format: str | None = None,
        ) -> dict[str, Any]:
            """Legacy alias for ConvertX target listing."""
            return await list_targets_payload(input_format, settings=settings)

        @mcp.tool(name="convert_file")
        async def legacy_convert_file(
            input_path: str,
            output_format: str,
            output_dir: str | None = None,
            converter: str | None = None,
            overwrite: bool = False,
        ) -> dict[str, Any]:
            """Legacy alias for ConvertX single-file conversion."""
            return await convert_file_payload(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )

        @mcp.tool(name="convert_batch")
        async def legacy_convert_batch(
            input_paths: list[str],
            output_format: str,
            output_dir: str | None = None,
            converter: str | None = None,
            overwrite: bool = False,
        ) -> dict[str, Any]:
            """Legacy alias for ConvertX batch conversion."""
            return await convert_batch_payload(
                input_paths=input_paths,
                output_format=output_format,
                output_dir=output_dir,
                converter=converter,
                overwrite=overwrite,
                settings=settings,
            )


BACKEND = ConvertXBackend()
