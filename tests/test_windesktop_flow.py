from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolhub.tools.windesktop import backend
from toolhub.tools.windesktop.client import ScreenshotArtifact


class FakeWinDesktopClient:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def health(self):
        return {
            "reachable": True,
            "base_url": self.settings.base_url,
            "service": "windesktop-bridge",
        }

    async def list_windows(self, *, include_hidden: bool = False, include_titles: bool = True):
        payload = {
            "ok": True,
            "windows": [
                {
                    "handle": 1001,
                    "title": None if not include_titles else "Example Window",
                    "title_redacted": not include_titles,
                    "title_length": 14,
                    "has_title": True,
                    "class_name": "Chrome_WidgetWin_1",
                    "pid": 4242,
                    "visible": True,
                    "rect": {
                        "left": 0,
                        "top": 0,
                        "right": 800,
                        "bottom": 600,
                        "width": 800,
                        "height": 600,
                    },
                }
            ],
        }
        filename = "windows-smoke.json"
        source_path = Path(self.settings.bridge_output_root) / filename
        source_path.write_text(json.dumps(payload), encoding="utf-8")
        return (
            {
                "ok": True,
                "filename": filename,
                "size_bytes": source_path.stat().st_size,
            },
            12,
        )

    async def screenshot(self, *, filename_stem: str | None = None, overwrite: bool = True):
        filename = f"{filename_stem or 'desktop-smoke'}.png"
        source_path = Path(self.settings.bridge_output_root) / filename
        if source_path.exists() and not overwrite:
            raise AssertionError("unexpected non-overwrite bridge screenshot request")
        source_path.write_bytes(b"fake-png-bytes")
        return ScreenshotArtifact(
            filename=filename,
            width=2258,
            height=1278,
            content_type="image/png",
            size_bytes=len(b"fake-png-bytes"),
            duration_ms=7,
        )

    async def focus_window(self, *, handle: int):
        return (
            {
                "ok": True,
                "handle": handle,
                "title": "Example Window",
                "rect": {
                    "left": 0,
                    "top": 0,
                    "right": 800,
                    "bottom": 600,
                    "width": 800,
                    "height": 600,
                },
            },
            5,
        )

    async def click(self, *, x: int, y: int, button: str = "left", double: bool = False):
        return (
            {
                "ok": True,
                "x": x,
                "y": y,
                "button": button,
                "double": double,
                "screen": {"width": 2258, "height": 1278},
            },
            6,
        )

    async def type_text(self, *, text: str, mode: str = "paste"):
        return (
            {
                "ok": True,
                "mode": mode,
                "char_count": len(text),
            },
            8,
        )

    async def hotkey(self, *, keys: list[str]):
        return (
            {
                "ok": True,
                "keys": keys,
            },
            4,
        )


@pytest.mark.asyncio
async def test_windesktop_health_payload(windesktop_settings, monkeypatch) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.health_payload(windesktop_settings)

    assert payload["ok"] is True
    assert payload["backend"] == "windesktop"
    assert payload["health"]["reachable"] is True


@pytest.mark.asyncio
async def test_windesktop_list_windows_includes_titles_by_default(
    windesktop_settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.list_windows_payload(settings=windesktop_settings)

    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["include_titles"] is True
    assert payload["windows"][0]["title"] == "Example Window"
    assert payload["windows"][0]["title_redacted"] is False


@pytest.mark.asyncio
async def test_windesktop_screenshot_writes_output_file(
    windesktop_settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)
    output_dir = Path(windesktop_settings.windesktop().allowed_output_roots[0])

    payload = await backend.screenshot_payload(
        output_dir=str(output_dir),
        filename_stem="desktop-smoke",
        overwrite=True,
        settings=windesktop_settings,
    )

    output_path = output_dir / "desktop-smoke.png"
    assert payload["ok"] is True
    assert payload["output"]["path"] == str(output_path)
    assert payload["width"] == 2258
    assert payload["height"] == 1278
    assert output_path.read_bytes() == b"fake-png-bytes"


@pytest.mark.asyncio
async def test_windesktop_focus_window_payload(windesktop_settings, monkeypatch) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.focus_window_payload(handle=1001, settings=windesktop_settings)

    assert payload["ok"] is True
    assert payload["handle"] == 1001
    assert payload["title"] == "Example Window"
    assert payload["rect"]["width"] == 800


@pytest.mark.asyncio
async def test_windesktop_click_payload(windesktop_settings, monkeypatch) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.click_payload(
        x=20,
        y=30,
        button="right",
        double=True,
        settings=windesktop_settings,
    )

    assert payload["ok"] is True
    assert payload["x"] == 20
    assert payload["y"] == 30
    assert payload["button"] == "right"
    assert payload["double"] is True


@pytest.mark.asyncio
async def test_windesktop_type_text_payload(windesktop_settings, monkeypatch) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.type_text_payload(
        text="hello",
        mode="paste",
        settings=windesktop_settings,
    )

    assert payload["ok"] is True
    assert payload["mode"] == "paste"
    assert payload["char_count"] == 5


@pytest.mark.asyncio
async def test_windesktop_hotkey_payload(windesktop_settings, monkeypatch) -> None:
    monkeypatch.setattr(backend, "WinDesktopClient", FakeWinDesktopClient)

    payload = await backend.hotkey_payload(keys=["Ctrl", "L"], settings=windesktop_settings)

    assert payload["ok"] is True
    assert payload["keys"] == ["ctrl", "l"]
