from __future__ import annotations

import getpass
import json
import os
import platform
import queue
import re
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from PIL import ImageGrab
from pydantic import BaseModel, Field


APP_VERSION = "0.3.0"
STARTED_AT = time.time()
TOKEN = os.getenv("WINDESKTOP_TOKEN", "").strip()
OUTPUT_DIR = os.getenv(
    "WINDESKTOP_OUTPUT_DIR",
    r"\\vmware-host\Shared Folders\HermesVMShare\WinDesktopOutput",
)
WINDOW_TITLE_TIMEOUT_SECONDS = float(os.getenv("WINDESKTOP_TITLE_TIMEOUT_SECONDS", "0.2"))
WINDOW_TITLE_LENGTH_TIMEOUT_SECONDS = float(
    os.getenv("WINDESKTOP_TITLE_LENGTH_TIMEOUT_SECONDS", "0.05")
)
SCREENSHOT_TIMEOUT_SECONDS = float(os.getenv("WINDESKTOP_SCREENSHOT_TIMEOUT_SECONDS", "10"))
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
MAX_TYPE_TEXT_CHARS = int(os.getenv("WINDESKTOP_MAX_TYPE_TEXT_CHARS", "4000"))
MAX_HOTKEY_KEYS = int(os.getenv("WINDESKTOP_MAX_HOTKEY_KEYS", "6"))
MAX_KEY_NAME_CHARS = int(os.getenv("WINDESKTOP_MAX_KEY_NAME_CHARS", "32"))
CLICK_MODES = {"left", "right", "middle", "double"}
HOTKEY_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "escape": "esc",
    "return": "enter",
    "win": "win",
    "windows": "win",
}


class FocusWindowRequest(BaseModel):
    handle: int = Field(gt=0)


class ClickRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: Literal["left", "right", "middle"] = "left"
    double: bool = False


class TypeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TYPE_TEXT_CHARS)
    mode: Literal["paste", "keys"] = "paste"


class HotkeyRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=MAX_HOTKEY_KEYS)


def _auth(authorization: Annotated[str | None, Header()] = None) -> None:
    if not TOKEN:
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _screen_size() -> dict[str, int | None]:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return {
            "width": int(user32.GetSystemMetrics(0)),
            "height": int(user32.GetSystemMetrics(1)),
        }
    except Exception:
        return {"width": None, "height": None}


def _run_with_timeout(
    func: Any,
    *,
    timeout_seconds: float,
    timeout_message: str,
) -> Any:
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            result_queue.put((True, func()))
        except Exception as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    try:
        ok, value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise HTTPException(
            status_code=504,
            detail={"message": timeout_message, "timeout_seconds": timeout_seconds},
        ) from exc
    if ok:
        return value
    raise value


def _output_root_status() -> dict[str, Any]:
    root = Path(OUTPUT_DIR)
    status: dict[str, Any] = {
        "path": str(root),
        "exists": root.exists(),
        "writable": False,
    }
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".windesktop-write-test-{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        status["exists"] = True
        status["writable"] = True
    except Exception as exc:
        status["error"] = str(exc)
    return status


def _output_root_status_with_timeout(timeout_seconds: float = 1.0) -> dict[str, Any]:
    """Check shared output directory without letting /health hang indefinitely."""
    try:
        return _run_with_timeout(
            _output_root_status,
            timeout_seconds=timeout_seconds,
            timeout_message="Timed out while checking the shared output directory.",
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return {
            "path": str(Path(OUTPUT_DIR)),
            "exists": False,
            "writable": False,
            "error": detail.get("message", str(exc.detail)),
            "timeout_seconds": detail.get("timeout_seconds", timeout_seconds),
        }
    except Exception as exc:
        return {
            "path": str(Path(OUTPUT_DIR)),
            "exists": False,
            "writable": False,
            "error": str(exc),
        }


def _validate_filename_stem(value: str | None) -> str:
    if value is None:
        return f"windesktop-screenshot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if not value or value != value.strip():
        raise HTTPException(
            status_code=400,
            detail={"message": "filename_stem must be a non-empty basename."},
        )
    if "/" in value or "\\" in value or "\x00" in value or value in {".", ".."}:
        raise HTTPException(
            status_code=400,
            detail={"message": "filename_stem must not contain path separators."},
        )
    if not SAFE_FILENAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail={"message": "filename_stem contains unsupported characters."},
        )
    return value


def _window_modules() -> tuple[Any, Any]:
    try:
        import win32gui
        import win32process
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "pywin32 is required for window enumeration.",
                "error": str(exc),
            },
        ) from exc
    return win32gui, win32process


def _input_modules() -> tuple[Any, Any, Any]:
    try:
        import win32api
        import win32con
        import win32clipboard
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "pywin32 is required for desktop input operations.",
                "error": str(exc),
            },
        ) from exc
    return win32api, win32con, win32clipboard


def _window_rect(win32gui: Any, hwnd: int) -> dict[str, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "width": max(int(right - left), 0),
        "height": max(int(bottom - top), 0),
    }


def _screen_bounds() -> tuple[int, int]:
    size = _screen_size()
    width = size.get("width")
    height = size.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise HTTPException(
            status_code=500,
            detail={"message": "Could not determine screen bounds."},
        )
    return width, height


def _normalize_hotkey_key(key: str) -> str:
    normalized = key.strip().lower()
    normalized = HOTKEY_ALIASES.get(normalized, normalized)
    if not normalized or len(normalized) > MAX_KEY_NAME_CHARS:
        raise HTTPException(
            status_code=400,
            detail={"message": "Hotkey keys must be short non-empty key names.", "key": key},
        )
    if not re.fullmatch(r"[a-z0-9_+.-]+", normalized):
        raise HTTPException(
            status_code=400,
            detail={"message": "Hotkey key contains unsupported characters.", "key": key},
        )
    return normalized


def _virtual_key(win32con: Any, key: str) -> int:
    special = {
        "ctrl": win32con.VK_CONTROL,
        "shift": win32con.VK_SHIFT,
        "alt": win32con.VK_MENU,
        "win": win32con.VK_LWIN,
        "enter": win32con.VK_RETURN,
        "esc": win32con.VK_ESCAPE,
        "tab": win32con.VK_TAB,
        "space": win32con.VK_SPACE,
        "backspace": win32con.VK_BACK,
        "delete": win32con.VK_DELETE,
        "home": win32con.VK_HOME,
        "end": win32con.VK_END,
        "left": win32con.VK_LEFT,
        "right": win32con.VK_RIGHT,
        "up": win32con.VK_UP,
        "down": win32con.VK_DOWN,
        "f1": win32con.VK_F1,
        "f2": win32con.VK_F2,
        "f3": win32con.VK_F3,
        "f4": win32con.VK_F4,
        "f5": win32con.VK_F5,
        "f6": win32con.VK_F6,
        "f7": win32con.VK_F7,
        "f8": win32con.VK_F8,
        "f9": win32con.VK_F9,
        "f10": win32con.VK_F10,
        "f11": win32con.VK_F11,
        "f12": win32con.VK_F12,
    }
    if key in special:
        return int(special[key])
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    raise HTTPException(
        status_code=400,
        detail={"message": "Unsupported hotkey key.", "key": key},
    )


def _focus_window(handle: int) -> dict[str, Any]:
    win32gui, _win32process = _window_modules()
    if not win32gui.IsWindow(handle):
        raise HTTPException(
            status_code=404,
            detail={"message": "Window handle was not found.", "handle": handle},
        )
    if win32gui.IsIconic(handle):
        win32gui.ShowWindow(handle, 9)  # SW_RESTORE
    try:
        win32gui.SetForegroundWindow(handle)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to focus window.", "handle": handle, "error": str(exc)},
        ) from exc
    return {
        "ok": True,
        "handle": int(handle),
        "title": _safe_window_title(win32gui, handle),
        "rect": _window_rect(win32gui, handle),
    }


def _click(x: int, y: int, button: str, *, double: bool) -> dict[str, Any]:
    width, height = _screen_bounds()
    if x >= width or y >= height:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Click coordinates are outside the current screen bounds.",
                "x": x,
                "y": y,
                "screen": {"width": width, "height": height},
            },
        )
    win32api, win32con, _win32clipboard = _input_modules()
    if button == "left":
        down, up = win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP
    elif button == "right":
        down, up = win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        down, up = win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP
    else:
        raise HTTPException(status_code=400, detail={"message": "Unsupported mouse button."})

    win32api.SetCursorPos((x, y))
    count = 2 if double else 1
    for _ in range(count):
        win32api.mouse_event(down, x, y, 0, 0)
        win32api.mouse_event(up, x, y, 0, 0)
        if count > 1:
            time.sleep(0.05)
    return {
        "ok": True,
        "x": x,
        "y": y,
        "button": button,
        "double": double,
        "screen": {"width": width, "height": height},
    }


def _set_clipboard_text(text: str) -> None:
    _win32api, _win32con, win32clipboard = _input_modules()
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _press_keys(keys: list[str]) -> None:
    win32api, win32con, _win32clipboard = _input_modules()
    virtual_keys = [_virtual_key(win32con, _normalize_hotkey_key(key)) for key in keys]
    for vk in virtual_keys:
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.01)
    for vk in reversed(virtual_keys):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)


def _type_text(text: str, mode: str) -> dict[str, Any]:
    if mode == "paste":
        _set_clipboard_text(text)
        _press_keys(["ctrl", "v"])
    elif mode == "keys":
        # ASCII-only fallback; paste is preferred for Chinese and long text.
        if any(ord(char) < 32 or ord(char) > 126 for char in text):
            raise HTTPException(
                status_code=400,
                detail={"message": "keys mode only supports printable ASCII. Use paste mode."},
            )
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys(text)
    else:
        raise HTTPException(status_code=400, detail={"message": "Unsupported type mode."})
    return {"ok": True, "mode": mode, "char_count": len(text)}


def _hotkey(keys: list[str]) -> dict[str, Any]:
    normalized = [_normalize_hotkey_key(key) for key in keys]
    _press_keys(normalized)
    return {"ok": True, "keys": normalized}


def _safe_window_title(win32gui: Any, hwnd: int) -> str | None:
    try:
        return _run_with_timeout(
            lambda: win32gui.GetWindowText(hwnd) or "",
            timeout_seconds=WINDOW_TITLE_TIMEOUT_SECONDS,
            timeout_message="Timed out while reading a window title.",
        )
    except Exception:
        return None


def _safe_window_title_length(win32gui: Any, hwnd: int) -> int:
    try:
        return int(
            _run_with_timeout(
                lambda: win32gui.GetWindowTextLength(hwnd) or 0,
                timeout_seconds=WINDOW_TITLE_LENGTH_TIMEOUT_SECONDS,
                timeout_message="Timed out while reading a window title length.",
            )
        )
    except Exception:
        return 0


def _enumerate_windows(*, include_hidden: bool, include_titles: bool) -> list[dict[str, Any]]:
    win32gui, win32process = _window_modules()
    windows: list[dict[str, Any]] = []

    def _callback(hwnd: int, _extra: Any) -> bool:
        visible = bool(win32gui.IsWindowVisible(hwnd))
        if not include_hidden and not visible:
            return True

        title = _safe_window_title(win32gui, hwnd) if include_titles else None
        title_length = len(title) if title is not None else _safe_window_title_length(win32gui, hwnd)
        class_name = win32gui.GetClassName(hwnd) or None
        _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        windows.append(
            {
                "handle": int(hwnd),
                "title": title if include_titles else None,
                "title_redacted": not include_titles and title_length > 0,
                "title_length": title_length,
                "has_title": title_length > 0,
                "class_name": class_name,
                "pid": int(pid) if pid else None,
                "visible": visible,
                "rect": _window_rect(win32gui, hwnd),
            }
        )
        return True

    win32gui.EnumWindows(_callback, None)
    return windows


def _capture_screenshot_file(*, filename_stem: str, overwrite: bool) -> dict[str, Any]:
    root = Path(OUTPUT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{filename_stem}.png"
    if target.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail={"message": "Screenshot output file already exists.", "filename": target.name},
        )

    image = ImageGrab.grab(all_screens=False)
    image.save(target, format="PNG")
    width, height = image.size
    size_bytes = target.stat().st_size
    return {
        "ok": True,
        "filename": target.name,
        "path": str(target),
        "width": width,
        "height": height,
        "content_type": "image/png",
        "size_bytes": size_bytes,
    }


def _write_windows_file(*, payload: dict[str, Any], filename_stem: str, overwrite: bool) -> dict[str, Any]:
    root = Path(OUTPUT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{filename_stem}.json"
    if target.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail={"message": "Windows output file already exists.", "filename": target.name},
        )
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {
        "filename": target.name,
        "path": str(target),
        "size_bytes": target.stat().st_size,
    }


app = FastAPI(title="WinDesktop Bridge", version=APP_VERSION)


@app.get("/health")
def health(
    compact: bool = Query(default=False),
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    screen = _screen_size()
    if compact:
        output_dir = _output_root_status_with_timeout(timeout_seconds=0.75)
        return {
            "ok": True,
            "service": "windesktop-bridge",
            "version": APP_VERSION,
            "screen": screen,
            "output_writable": bool(output_dir.get("writable")),
            "output_dir": output_dir,
            "uptime_seconds": int(time.time() - STARTED_AT),
        }

    payload = {
        "ok": True,
        "service": "windesktop-bridge",
        "version": APP_VERSION,
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "screen": screen,
        "output_dir": _output_root_status_with_timeout(timeout_seconds=2.0),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "auth_required": bool(TOKEN),
    }
    return payload


@app.get("/windows")
def windows(
    include_hidden: bool = Query(default=False),
    include_titles: bool = Query(default=True),
    inline: bool = Query(default=False),
    filename_stem: str | None = Query(default=None),
    overwrite: bool = Query(default=True),
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    items = _enumerate_windows(
        include_hidden=include_hidden,
        include_titles=include_titles,
    )
    payload = {
        "ok": True,
        "count": len(items),
        "include_hidden": include_hidden,
        "include_titles": include_titles,
        "windows": items,
    }
    if inline:
        return payload

    stem = _validate_filename_stem(filename_stem) if filename_stem else (
        f"windesktop-windows-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    output = _write_windows_file(
        payload=payload,
        filename_stem=stem,
        overwrite=overwrite,
    )
    return {
        "ok": True,
        "count": len(items),
        "include_hidden": include_hidden,
        "include_titles": include_titles,
        "filename": output["filename"],
    }


@app.get("/screenshot")
def screenshot(
    filename_stem: str | None = Query(default=None),
    overwrite: bool = Query(default=False),
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    stem = _validate_filename_stem(filename_stem)
    try:
        payload = _run_with_timeout(
            lambda: _capture_screenshot_file(filename_stem=stem, overwrite=overwrite),
            timeout_seconds=SCREENSHOT_TIMEOUT_SECONDS,
            timeout_message="Timed out while writing the screenshot file.",
        )
        return {
            "ok": payload["ok"],
            "filename": payload["filename"],
            "width": payload["width"],
            "height": payload["height"],
            "content_type": payload["content_type"],
            "size_bytes": payload["size_bytes"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to write screenshot file.", "error": str(exc)},
        ) from exc


@app.post("/focus-window")
def focus_window(
    request: FocusWindowRequest,
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    return _focus_window(request.handle)


@app.post("/click")
def click(
    request: ClickRequest,
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    return _click(request.x, request.y, request.button, double=request.double)


@app.post("/type")
def type_text(
    request: TypeRequest,
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    return _type_text(request.text, request.mode)


@app.post("/hotkey")
def hotkey(
    request: HotkeyRequest,
    _authorized: None = Depends(_auth),
) -> dict[str, Any]:
    return _hotkey(request.keys)


def main() -> None:
    host = os.getenv("WINDESKTOP_HOST", "0.0.0.0")
    port = int(os.getenv("WINDESKTOP_PORT", "18787"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
