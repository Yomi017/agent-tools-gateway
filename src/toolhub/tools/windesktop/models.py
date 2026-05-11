from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ...models import OutputFile


class ListWindowsRequest(BaseModel):
    include_hidden: bool = False
    include_titles: bool = True


class ScreenshotRequest(BaseModel):
    output_dir: str | None = None
    filename_stem: str | None = None
    overwrite: bool = False


class FocusWindowRequest(BaseModel):
    handle: int = Field(gt=0)


class ClickRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: Literal["left", "right", "middle"] = "left"
    double: bool = False


class TypeTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["paste", "keys"] = "paste"


class HotkeyRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=6)

    @field_validator("keys")
    @classmethod
    def _normalize_keys(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            key = str(item).strip().lower()
            if not key or len(key) > 32:
                raise ValueError("hotkey keys must be short non-empty strings")
            normalized.append(key)
        return normalized


class WindowRect(BaseModel):
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int


class WindowInfo(BaseModel):
    handle: int
    title: str | None = None
    title_redacted: bool = False
    title_length: int = 0
    has_title: bool = False
    class_name: str | None = None
    pid: int | None = None
    visible: bool = True
    rect: WindowRect


class ListWindowsSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    count: int
    include_hidden: bool
    include_titles: bool
    windows: list[WindowInfo]
    duration_ms: int


class ScreenshotSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    output: OutputFile
    width: int | None = None
    height: int | None = None
    content_type: str
    size_bytes: int
    duration_ms: int


class HealthSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    health: dict[str, Any]


class FocusWindowSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    handle: int
    title: str | None = None
    rect: WindowRect | None = None
    duration_ms: int


class ClickSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    x: int
    y: int
    button: str
    double: bool
    screen: dict[str, Any] | None = None
    duration_ms: int


class TypeTextSuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    mode: str
    char_count: int
    duration_ms: int


class HotkeySuccess(BaseModel):
    ok: bool = True
    backend: str = "windesktop"
    keys: list[str]
    duration_ms: int
