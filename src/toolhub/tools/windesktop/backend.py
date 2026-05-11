from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from ...config import Settings, WinDesktopRuntimeSettings, get_settings
from ...errors import CaptureLimitError, OutputExistsError, PathNotAllowedError, error_payload
from ...models import OutputFile
from ...security import safe_write_output_file, validate_filename_stem
from .client import WinDesktopClient
from .models import (
    ClickRequest,
    ClickSuccess,
    FocusWindowRequest,
    FocusWindowSuccess,
    HealthSuccess,
    HotkeyRequest,
    HotkeySuccess,
    ListWindowsRequest,
    ListWindowsSuccess,
    ScreenshotRequest,
    ScreenshotSuccess,
    TypeTextRequest,
    TypeTextSuccess,
    WindowInfo,
)


backend_key = "windesktop"


class WinDesktopOutputPolicy:
    def __init__(self, settings: WinDesktopRuntimeSettings) -> None:
        self.settings = settings
        self.output_roots = [self._root(root) for root in settings.allowed_output_roots]

    @staticmethod
    def _root(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _require_under(self, path: Path, roots: list[Path], kind: str) -> Path:
        resolved = path.expanduser().resolve(strict=False)
        if any(self._is_under(resolved, root) for root in roots):
            return resolved
        raise PathNotAllowedError(
            f"{kind} path is outside allowed roots: {path}",
            details={"path": str(path), "allowed_roots": [str(root) for root in roots]},
        )

    def validate_output_dir(self, path: str | Path | None = None) -> Path:
        raw_path = Path(path).expanduser() if path else self.output_roots[0]
        resolved = self._require_under(raw_path, self.output_roots, "output")
        resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise PathNotAllowedError(
                f"Output path is not a directory: {raw_path}",
                code="output_not_dir",
                details={"path": str(raw_path)},
            )
        return resolved

    def build_screenshot_path(
        self,
        *,
        output_dir: str | Path | None = None,
        filename_stem: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        directory = self.validate_output_dir(output_dir)
        stem = validate_filename_stem(filename_stem) or default_screenshot_filename()
        target = directory.joinpath(f"{stem}.png").resolve(strict=False)
        self._require_under(target, [directory.resolve(strict=False)], "output file")
        self._require_under(target, self.output_roots, "output file")
        if target.exists() and not overwrite:
            raise OutputExistsError(
                f"Output file already exists: {target}",
                details={"path": str(target)},
            )
        return target

    def validate_bridge_output_file(self, filename: str) -> Path:
        if not filename or "/" in filename or "\\" in filename or "\x00" in filename:
            raise PathNotAllowedError(
                "Bridge screenshot filename is not a safe basename.",
                code="unsafe_bridge_output",
                details={"filename": filename},
            )
        root = self._root(self.settings.bridge_output_root)
        source = root.joinpath(filename).resolve(strict=False)
        self._require_under(source, [root], "bridge output file")
        if not source.exists():
            raise PathNotAllowedError(
                f"Bridge screenshot file does not exist: {source}",
                code="bridge_output_not_found",
                details={"path": str(source), "filename": filename},
            )
        if not source.is_file():
            raise PathNotAllowedError(
                f"Bridge screenshot path is not a regular file: {source}",
                code="bridge_output_not_file",
                details={"path": str(source), "filename": filename},
            )
        return source


def default_screenshot_filename() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"windesktop-screenshot-{timestamp}"


def _runtime(settings: Settings | None = None) -> WinDesktopRuntimeSettings:
    return (settings or get_settings()).windesktop()


def _load_bridge_json_file(policy: WinDesktopOutputPolicy, filename: str) -> dict[str, Any]:
    source = policy.validate_bridge_output_file(filename)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PathNotAllowedError(
            "Bridge output file did not contain a JSON object.",
            code="invalid_bridge_output",
            details={"path": str(source), "filename": filename},
        ) from exc
    if not isinstance(payload, dict):
        raise PathNotAllowedError(
            "Bridge output file did not contain a JSON object.",
            code="invalid_bridge_output",
            details={"path": str(source), "filename": filename},
        )
    return payload


async def health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    return await client.health()


async def list_windows(
    *,
    include_hidden: bool = False,
    include_titles: bool = True,
    settings: Settings | None = None,
) -> ListWindowsSuccess:
    request = ListWindowsRequest(
        include_hidden=include_hidden,
        include_titles=include_titles,
    )
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    payload, duration_ms = await client.list_windows(
        include_hidden=request.include_hidden,
        include_titles=request.include_titles,
    )
    raw_windows = payload.get("windows") if isinstance(payload, dict) else []
    if not isinstance(raw_windows, list):
        filename = payload.get("filename") if isinstance(payload, dict) else None
        if isinstance(filename, str) and filename:
            file_payload = _load_bridge_json_file(WinDesktopOutputPolicy(runtime), filename)
            raw_windows = file_payload.get("windows")
    if not isinstance(raw_windows, list):
        raw_windows = []
    windows = [
        WindowInfo.model_validate(item)
        for item in raw_windows
        if isinstance(item, dict)
    ]
    return ListWindowsSuccess(
        count=len(windows),
        include_hidden=request.include_hidden,
        include_titles=request.include_titles,
        windows=windows,
        duration_ms=duration_ms,
    )


async def screenshot(
    *,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> ScreenshotSuccess:
    request = ScreenshotRequest(
        output_dir=output_dir,
        filename_stem=filename_stem,
        overwrite=overwrite,
    )
    runtime = _runtime(settings)
    policy = WinDesktopOutputPolicy(runtime)
    output_path = policy.build_screenshot_path(
        output_dir=request.output_dir,
        filename_stem=request.filename_stem,
        overwrite=request.overwrite,
    )

    client = WinDesktopClient(runtime)
    artifact = await client.screenshot(
        filename_stem=output_path.stem,
        overwrite=True,
    )
    size_bytes = artifact.size_bytes
    if size_bytes > runtime.max_screenshot_bytes:
        raise CaptureLimitError(
            "WinDesktop screenshot exceeds max_screenshot_bytes.",
            details={
                "limit": runtime.max_screenshot_bytes,
                "actual": size_bytes,
            },
        )

    source_path = policy.validate_bridge_output_file(artifact.filename)
    actual_size = source_path.stat().st_size
    if actual_size > runtime.max_screenshot_bytes:
        raise CaptureLimitError(
            "WinDesktop screenshot file exceeds max_screenshot_bytes.",
            details={
                "limit": runtime.max_screenshot_bytes,
                "actual": actual_size,
                "path": str(source_path),
            },
        )
    if actual_size != size_bytes:
        size_bytes = actual_size

    content = source_path.read_bytes()
    safe_write_output_file(output_path, content, overwrite=request.overwrite)
    return ScreenshotSuccess(
        output=OutputFile(path=str(output_path), filename=output_path.name),
        width=artifact.width,
        height=artifact.height,
        content_type=artifact.content_type,
        size_bytes=size_bytes,
        duration_ms=artifact.duration_ms,
    )


async def focus_window(
    *,
    handle: int,
    settings: Settings | None = None,
) -> FocusWindowSuccess:
    request = FocusWindowRequest(handle=handle)
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    payload, duration_ms = await client.focus_window(handle=request.handle)
    return FocusWindowSuccess(
        handle=int(payload.get("handle") or request.handle),
        title=payload.get("title") if isinstance(payload.get("title"), str) else None,
        rect=payload.get("rect") if isinstance(payload.get("rect"), dict) else None,
        duration_ms=duration_ms,
    )


async def click(
    *,
    x: int,
    y: int,
    button: str = "left",
    double: bool = False,
    settings: Settings | None = None,
) -> ClickSuccess:
    request = ClickRequest(x=x, y=y, button=button, double=double)
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    payload, duration_ms = await client.click(
        x=request.x,
        y=request.y,
        button=request.button,
        double=request.double,
    )
    return ClickSuccess(
        x=int(payload.get("x") or request.x),
        y=int(payload.get("y") or request.y),
        button=str(payload.get("button") or request.button),
        double=bool(payload.get("double", request.double)),
        screen=payload.get("screen") if isinstance(payload.get("screen"), dict) else None,
        duration_ms=duration_ms,
    )


async def type_text(
    *,
    text: str,
    mode: str = "paste",
    settings: Settings | None = None,
) -> TypeTextSuccess:
    request = TypeTextRequest(text=text, mode=mode)
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    payload, duration_ms = await client.type_text(text=request.text, mode=request.mode)
    return TypeTextSuccess(
        mode=str(payload.get("mode") or request.mode),
        char_count=int(payload.get("char_count") or len(request.text)),
        duration_ms=duration_ms,
    )


async def hotkey(
    *,
    keys: list[str],
    settings: Settings | None = None,
) -> HotkeySuccess:
    request = HotkeyRequest(keys=keys)
    runtime = _runtime(settings)
    client = WinDesktopClient(runtime)
    payload, duration_ms = await client.hotkey(keys=request.keys)
    raw_keys = payload.get("keys")
    return HotkeySuccess(
        keys=[str(key) for key in raw_keys] if isinstance(raw_keys, list) else request.keys,
        duration_ms=duration_ms,
    )


async def health_payload(settings: Settings | None = None) -> dict[str, Any]:
    try:
        return HealthSuccess(health=await health(settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def list_windows_payload(
    *,
    include_hidden: bool = False,
    include_titles: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await list_windows(
                include_hidden=include_hidden,
                include_titles=include_titles,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def screenshot_payload(
    *,
    output_dir: str | None = None,
    filename_stem: str | None = None,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await screenshot(
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def focus_window_payload(
    *,
    handle: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (await focus_window(handle=handle, settings=settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def click_payload(
    *,
    x: int,
    y: int,
    button: str = "left",
    double: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (
            await click(
                x=x,
                y=y,
                button=button,
                double=double,
                settings=settings,
            )
        ).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def type_text_payload(
    *,
    text: str,
    mode: str = "paste",
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (await type_text(text=text, mode=mode, settings=settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)


async def hotkey_payload(
    *,
    keys: list[str],
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        return (await hotkey(keys=keys, settings=settings)).model_dump()
    except Exception as exc:
        return error_payload(exc)


class WinDesktopBackend:
    key = backend_key

    def is_enabled(self, settings: Settings) -> bool:
        return settings.windesktop().enabled

    async def health(self, settings: Settings) -> dict[str, Any]:
        return await health(settings)

    def register_api(
        self,
        app: FastAPI,
        auth_dependency: Callable[..., None],
        json_response: Callable[[object], JSONResponse],
        settings: Settings,
    ) -> None:
        router = APIRouter(prefix="/v1/windesktop", tags=["windesktop"])

        @router.post("/list-windows")
        async def list_windows_route(
            request: ListWindowsRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await list_windows_payload(
                    include_hidden=request.include_hidden,
                    include_titles=request.include_titles,
                    settings=settings,
                )
            )

        @router.post("/screenshot")
        async def screenshot_route(
            request: ScreenshotRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await screenshot_payload(
                    output_dir=request.output_dir,
                    filename_stem=request.filename_stem,
                    overwrite=request.overwrite,
                    settings=settings,
                )
            )

        @router.post("/focus-window")
        async def focus_window_route(
            request: FocusWindowRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await focus_window_payload(handle=request.handle, settings=settings)
            )

        @router.post("/click")
        async def click_route(
            request: ClickRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await click_payload(
                    x=request.x,
                    y=request.y,
                    button=request.button,
                    double=request.double,
                    settings=settings,
                )
            )

        @router.post("/type")
        async def type_route(
            request: TypeTextRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await type_text_payload(
                    text=request.text,
                    mode=request.mode,
                    settings=settings,
                )
            )

        @router.post("/hotkey")
        async def hotkey_route(
            request: HotkeyRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await hotkey_payload(keys=request.keys, settings=settings)
            )

        app.include_router(router)

    def register_mcp(self, mcp: FastMCP, settings: Settings) -> None:
        @mcp.tool(name="windesktop_health")
        async def windesktop_health() -> dict[str, Any]:
            """Check reachability of the Windows VM desktop bridge."""
            return await health_payload(settings)

        @mcp.tool(name="windesktop_list_windows")
        async def windesktop_list_windows(
            include_hidden: bool = False,
            include_titles: bool = True,
        ) -> dict[str, Any]:
            """List Windows VM top-level windows; titles are included by default."""
            return await list_windows_payload(
                include_hidden=include_hidden,
                include_titles=include_titles,
                settings=settings,
            )

        @mcp.tool(name="windesktop_screenshot")
        async def windesktop_screenshot(
            output_dir: str | None = None,
            filename_stem: str | None = None,
            overwrite: bool = False,
        ) -> dict[str, Any]:
            """Capture the current Windows VM desktop as a PNG output file."""
            return await screenshot_payload(
                output_dir=output_dir,
                filename_stem=filename_stem,
                overwrite=overwrite,
                settings=settings,
            )

        @mcp.tool(name="windesktop_focus_window")
        async def windesktop_focus_window(handle: int) -> dict[str, Any]:
            """Focus a Windows VM window by handle. Requires user confirmation before use."""
            return await focus_window_payload(handle=handle, settings=settings)

        @mcp.tool(name="windesktop_click")
        async def windesktop_click(
            x: int,
            y: int,
            button: str = "left",
            double: bool = False,
        ) -> dict[str, Any]:
            """Click the Windows VM desktop. Requires user confirmation before use."""
            return await click_payload(
                x=x,
                y=y,
                button=button,
                double=double,
                settings=settings,
            )

        @mcp.tool(name="windesktop_type")
        async def windesktop_type(text: str, mode: str = "paste") -> dict[str, Any]:
            """Type text into the focused Windows VM app. Requires user confirmation before use."""
            return await type_text_payload(text=text, mode=mode, settings=settings)

        @mcp.tool(name="windesktop_hotkey")
        async def windesktop_hotkey(keys: list[str]) -> dict[str, Any]:
            """Send a hotkey to the Windows VM. Requires user confirmation before use."""
            return await hotkey_payload(keys=keys, settings=settings)


BACKEND = WinDesktopBackend()
