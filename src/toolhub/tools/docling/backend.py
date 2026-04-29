from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from ...config import DoclingRuntimeSettings, Settings, get_settings
from ...errors import OutputExistsError, error_payload
from ...models import OutputFile
from ...security import PathPolicy, WebCapturePathPolicy, safe_write_output_file
from .client import DoclingClient
from .models import (
    DOCLING_OUTPUT_EXTENSIONS,
    DoclingCheckSuccess,
    DoclingConvertSuccess,
    DoclingRequest,
)


backend_key = "docling"


def _runtime(settings: Settings | None = None) -> DoclingRuntimeSettings:
    return (settings or get_settings()).docling()


def _effective_options(
    *,
    output_format: str,
    do_ocr: bool | None,
    force_ocr: bool | None,
    ocr_engine: str | None,
    pdf_backend: str | None,
    table_mode: str | None,
    image_export_mode: str | None,
    include_images: bool | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"output_format": output_format}
    for key, value in (
        ("do_ocr", do_ocr),
        ("force_ocr", force_ocr),
        ("ocr_engine", ocr_engine),
        ("pdf_backend", pdf_backend),
        ("table_mode", table_mode),
        ("image_export_mode", image_export_mode),
        ("include_images", include_images),
    ):
        if value is not None:
            options[key] = value
    return options


def _build_output_path(
    runtime: DoclingRuntimeSettings,
    *,
    input_file: Path,
    output_format: str,
    output_dir: str | None,
    filename_stem: str | None,
    overwrite: bool,
) -> Path:
    extension = DOCLING_OUTPUT_EXTENSIONS[output_format]
    output_policy = WebCapturePathPolicy(runtime)
    directory = output_policy.validate_output_dir(output_dir)
    stem = output_policy.validate_filename_stem(filename_stem) or input_file.stem
    target = directory / f"{stem}.{extension}"
    if target.exists() and not overwrite:
        raise OutputExistsError(
            f"Output file already exists: {target}",
            details={"path": str(target)},
        )
    return target


async def health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = _runtime(settings)
    client = DoclingClient(runtime)
    return await client.health()


async def check_file(
    *,
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    do_ocr: bool | None = None,
    force_ocr: bool | None = None,
    ocr_engine: str | None = None,
    pdf_backend: str | None = None,
    table_mode: str | None = None,
    image_export_mode: str | None = None,
    include_images: bool | None = None,
    settings: Settings | None = None,
) -> DoclingCheckSuccess:
    runtime = _runtime(settings)
    policy = PathPolicy(runtime)
    input_file = policy.validate_input_file(input_path)
    planned_output = _build_output_path(
        runtime,
        input_file=input_file,
        output_format=output_format,
        output_dir=output_dir,
        filename_stem=filename_stem,
        overwrite=overwrite,
    )
    return DoclingCheckSuccess(
        input_path=str(input_file),
        planned_output_path=str(planned_output),
        effective_options=_effective_options(
            output_format=output_format,
            do_ocr=do_ocr,
            force_ocr=force_ocr,
            ocr_engine=ocr_engine,
            pdf_backend=pdf_backend,
            table_mode=table_mode,
            image_export_mode=image_export_mode,
            include_images=include_images,
        ),
    )


async def convert_file(
    *,
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    do_ocr: bool | None = None,
    force_ocr: bool | None = None,
    ocr_engine: str | None = None,
    pdf_backend: str | None = None,
    table_mode: str | None = None,
    image_export_mode: str | None = None,
    include_images: bool | None = None,
    settings: Settings | None = None,
) -> DoclingConvertSuccess:
    runtime = _runtime(settings)
    policy = PathPolicy(runtime)
    input_file = policy.validate_input_file(input_path)
    output_path = _build_output_path(
        runtime,
        input_file=input_file,
        output_format=output_format,
        output_dir=output_dir,
        filename_stem=filename_stem,
        overwrite=overwrite,
    )

    client = DoclingClient(runtime)
    task_id, content, duration_ms = await client.convert_file(
        input_file,
        output_format=output_format,
        do_ocr=do_ocr,
        force_ocr=force_ocr,
        ocr_engine=ocr_engine,
        pdf_backend=pdf_backend,
        table_mode=table_mode,
        image_export_mode=image_export_mode,
        include_images=include_images,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_output_file(output_path, content, overwrite=overwrite)

    return DoclingConvertSuccess(
        input_path=str(input_file),
        output_format=output_format,
        task_id=task_id,
        output=OutputFile(path=str(output_path), filename=output_path.name),
        duration_ms=duration_ms,
    )


async def health_payload(settings: Settings | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "backend": backend_key, "health": await health(settings)}
    except Exception as exc:
        return error_payload(exc)


async def check_file_payload(
    *,
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    do_ocr: bool | None = None,
    force_ocr: bool | None = None,
    ocr_engine: str | None = None,
    pdf_backend: str | None = None,
    table_mode: str | None = None,
    image_export_mode: str | None = None,
    include_images: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await check_file(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                image_export_mode=image_export_mode,
                include_images=include_images,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def convert_file_payload(
    *,
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    do_ocr: bool | None = None,
    force_ocr: bool | None = None,
    ocr_engine: str | None = None,
    pdf_backend: str | None = None,
    table_mode: str | None = None,
    image_export_mode: str | None = None,
    include_images: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await convert_file(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                image_export_mode=image_export_mode,
                include_images=include_images,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


class DoclingBackend:
    key = backend_key

    def is_enabled(self, settings: Settings) -> bool:
        return settings.docling().enabled

    async def health(self, settings: Settings) -> dict[str, Any]:
        return await health(settings)

    def register_api(
        self,
        app: FastAPI,
        auth_dependency: Callable[..., None],
        json_response: Callable[[object], JSONResponse],
        settings: Settings,
    ) -> None:
        router = APIRouter(prefix="/v1/docling", tags=["docling"])

        @router.post("/check")
        async def check_route(
            request: DoclingRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await check_file_payload(
                    input_path=request.input_path,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    filename_stem=request.filename_stem,
                    overwrite=request.overwrite,
                    do_ocr=request.do_ocr,
                    force_ocr=request.force_ocr,
                    ocr_engine=request.ocr_engine,
                    pdf_backend=request.pdf_backend,
                    table_mode=request.table_mode,
                    image_export_mode=request.image_export_mode,
                    include_images=request.include_images,
                    settings=settings,
                )
            )

        @router.post("/convert")
        async def convert_route(
            request: DoclingRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await convert_file_payload(
                    input_path=request.input_path,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    filename_stem=request.filename_stem,
                    overwrite=request.overwrite,
                    do_ocr=request.do_ocr,
                    force_ocr=request.force_ocr,
                    ocr_engine=request.ocr_engine,
                    pdf_backend=request.pdf_backend,
                    table_mode=request.table_mode,
                    image_export_mode=request.image_export_mode,
                    include_images=request.include_images,
                    settings=settings,
                )
            )

        app.include_router(router)

    def register_mcp(self, mcp: FastMCP, settings: Settings) -> None:
        @mcp.tool(name="docling_health")
        async def docling_health() -> dict[str, Any]:
            """Check Docling Serve reachability and version info."""
            return await health_payload(settings)

        @mcp.tool(name="docling_check_file")
        async def docling_check_file(
            input_path: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            do_ocr: bool | None = None,
            force_ocr: bool | None = None,
            ocr_engine: str | None = None,
            pdf_backend: str | None = None,
            table_mode: str | None = None,
            image_export_mode: str | None = None,
            include_images: bool | None = None,
        ) -> dict[str, Any]:
            """Validate a Docling conversion request without writing any files."""
            return await check_file_payload(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                image_export_mode=image_export_mode,
                include_images=include_images,
                settings=settings,
            )

        @mcp.tool(name="docling_convert_file")
        async def docling_convert_file(
            input_path: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            do_ocr: bool | None = None,
            force_ocr: bool | None = None,
            ocr_engine: str | None = None,
            pdf_backend: str | None = None,
            table_mode: str | None = None,
            image_export_mode: str | None = None,
            include_images: bool | None = None,
        ) -> dict[str, Any]:
            """Convert one local document through Docling Serve."""
            return await convert_file_payload(
                input_path=input_path,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                image_export_mode=image_export_mode,
                include_images=include_images,
                settings=settings,
            )


BACKEND = DoclingBackend()
