from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from ...config import Settings, WebCaptureRuntimeSettings, get_settings
from ...errors import OutputExistsError, error_payload
from ...models import OutputFile
from ...security import WebCapturePathPolicy, validate_web_url
from .client import DEFAULT_WAIT_UNTIL, WebCaptureClient
from .models import CaptureRequest, CaptureSuccess, CheckSuccess, NavigationStatus


backend_key = "webcapture"


def _runtime(settings: Settings | None = None) -> WebCaptureRuntimeSettings:
    return (settings or get_settings()).webcapture()


def _effective_options(
    *,
    output_format: str,
    wait_until: str | None,
    full_page: bool | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "output_format": output_format,
        "wait_until": wait_until or DEFAULT_WAIT_UNTIL,
    }
    if output_format == "png":
        options["full_page"] = True if full_page is None else full_page
    return options


def _safe_write_output_file(output_path: Path, content: bytes, *, overwrite: bool) -> None:
    directory = output_path.parent
    target_name = output_path.name
    temp_name = f".{target_name}.tmp-{secrets.token_hex(8)}"
    file_mode = 0o644
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    dir_fd = os.open(directory, dir_flags)
    temp_created = False

    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            file_mode,
            dir_fd=dir_fd,
        )
        temp_created = True
        with os.fdopen(temp_fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), file_mode)
            os.fsync(handle.fileno())

        if overwrite:
            os.replace(temp_name, target_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            temp_created = False
        else:
            try:
                os.link(
                    temp_name,
                    target_name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise OutputExistsError(
                    f"Output file already exists: {output_path}",
                    details={"path": str(output_path)},
                ) from exc
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=dir_fd)
                temp_created = False

        os.fsync(dir_fd)
    finally:
        if temp_created:
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=dir_fd)
        os.close(dir_fd)


async def health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = _runtime(settings)
    client = WebCaptureClient(runtime)
    return await client.health()


async def check_url(
    *,
    url: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    wait_until: str | None = None,
    full_page: bool | None = None,
    settings: Settings | None = None,
) -> CheckSuccess:
    runtime = _runtime(settings)
    checked = validate_web_url(url, block_private_networks=runtime.block_private_networks)
    policy = WebCapturePathPolicy(runtime)
    planned_output = policy.build_output_path(
        normalized_url=checked.normalized_url,
        output_format=output_format,
        output_dir=output_dir,
        filename_stem=filename_stem,
        overwrite=overwrite,
    )
    return CheckSuccess(
        normalized_url=checked.normalized_url,
        planned_output_path=str(planned_output),
        effective_options=_effective_options(
            output_format=output_format,
            wait_until=wait_until,
            full_page=full_page,
        ),
    )


async def capture_url(
    *,
    url: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    wait_until: str | None = None,
    full_page: bool | None = None,
    settings: Settings | None = None,
) -> CaptureSuccess:
    runtime = _runtime(settings)
    checked = validate_web_url(url, block_private_networks=runtime.block_private_networks)
    policy = WebCapturePathPolicy(runtime)
    output_path = policy.build_output_path(
        normalized_url=checked.normalized_url,
        output_format=output_format,
        output_dir=output_dir,
        filename_stem=filename_stem,
        overwrite=overwrite,
    )

    client = WebCaptureClient(runtime)
    artifact, duration_ms = await client.capture(
        url=checked.normalized_url,
        output_format=output_format,
        wait_until=wait_until,
        full_page=full_page,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_output_file(output_path, artifact.content, overwrite=overwrite)

    return CaptureSuccess(
        requested_url=url,
        final_url=artifact.final_url,
        title=artifact.title,
        output=OutputFile(path=str(output_path), filename=Path(output_path).name),
        duration_ms=duration_ms,
        navigation_status=NavigationStatus.model_validate(artifact.navigation_status),
    )


async def health_payload(settings: Settings | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "backend": backend_key, "health": await health(settings)}
    except Exception as exc:
        return error_payload(exc)


async def check_url_payload(
    *,
    url: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    wait_until: str | None = None,
    full_page: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await check_url(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def capture_url_payload(
    *,
    url: str,
    output_format: str,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    wait_until: str | None = None,
    full_page: bool | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await capture_url(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


class WebCaptureBackend:
    key = backend_key

    def is_enabled(self, settings: Settings) -> bool:
        return settings.webcapture().enabled

    async def health(self, settings: Settings) -> dict[str, Any]:
        return await health(settings)

    def register_api(
        self,
        app: FastAPI,
        auth_dependency: Callable[..., None],
        json_response: Callable[[object], JSONResponse],
        settings: Settings,
    ) -> None:
        router = APIRouter(prefix="/v1/webcapture", tags=["webcapture"])

        @router.post("/check")
        async def check_route(
            request: CaptureRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await check_url_payload(
                    url=request.url,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    filename_stem=request.filename_stem,
                    overwrite=request.overwrite,
                    wait_until=request.wait_until,
                    full_page=request.full_page,
                    settings=settings,
                )
            )

        @router.post("/capture")
        async def capture_route(
            request: CaptureRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await capture_url_payload(
                    url=request.url,
                    output_format=request.output_format,
                    output_dir=request.output_dir,
                    filename_stem=request.filename_stem,
                    overwrite=request.overwrite,
                    wait_until=request.wait_until,
                    full_page=request.full_page,
                    settings=settings,
                )
            )

        app.include_router(router)

    def register_mcp(self, mcp: FastMCP, settings: Settings) -> None:
        @mcp.tool(name="webcapture_health")
        async def webcapture_health() -> dict[str, Any]:
            """Check Browserless reachability for the webcapture backend."""
            return await health_payload(settings)

        @mcp.tool(name="webcapture_check_url")
        async def webcapture_check_url(
            url: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            wait_until: str | None = None,
            full_page: bool | None = None,
        ) -> dict[str, Any]:
            """Validate a webpage capture request without writing any files."""
            return await check_url_payload(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )

        @mcp.tool(name="webcapture_capture_url")
        async def webcapture_capture_url(
            url: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            wait_until: str | None = None,
            full_page: bool | None = None,
        ) -> dict[str, Any]:
            """Capture a single webpage into pdf, png, or md."""
            return await capture_url_payload(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )

        @mcp.tool(name="check_webpage_capture")
        async def legacy_check_webpage_capture(
            url: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            wait_until: str | None = None,
            full_page: bool | None = None,
        ) -> dict[str, Any]:
            """Legacy alias for webcapture request validation."""
            return await check_url_payload(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )

        @mcp.tool(name="capture_webpage")
        async def legacy_capture_webpage(
            url: str,
            output_format: str,
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
            wait_until: str | None = None,
            full_page: bool | None = None,
        ) -> dict[str, Any]:
            """Legacy alias for webcapture execution."""
            return await capture_url_payload(
                url=url,
                output_format=output_format,
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                wait_until=wait_until,
                full_page=full_page,
                settings=settings,
            )


BACKEND = WebCaptureBackend()
