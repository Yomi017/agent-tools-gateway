from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from ...models import OutputFile


SUPPORTED_CAPTURE_FORMATS = frozenset({"pdf", "png", "md"})
SUPPORTED_WAIT_UNTIL = frozenset({"commit", "domcontentloaded", "load", "networkidle"})


def normalize_capture_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if normalized not in SUPPORTED_CAPTURE_FORMATS:
        raise ValueError(
            f"output_format must be one of {', '.join(sorted(SUPPORTED_CAPTURE_FORMATS))}"
        )
    return normalized


def normalize_wait_until(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_WAIT_UNTIL:
        raise ValueError(
            f"wait_until must be one of {', '.join(sorted(SUPPORTED_WAIT_UNTIL))}"
        )
    return normalized


class CaptureRequest(BaseModel):
    url: str
    output_format: str
    output_dir: str | None = None
    filename_stem: str | None = None
    overwrite: bool = False
    wait_until: str | None = None
    full_page: bool | None = None

    @field_validator("output_format", mode="before")
    @classmethod
    def _normalize_output_format(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("output_format must be a string")
        return normalize_capture_format(value)

    @field_validator("wait_until", mode="before")
    @classmethod
    def _normalize_wait_until(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("wait_until must be a string")
        return normalize_wait_until(value)


class NavigationStatus(BaseModel):
    status: int | None = None
    ok: bool | None = None
    url: str | None = None


class CheckSuccess(BaseModel):
    ok: bool = True
    backend: str = "webcapture"
    check: bool = True
    normalized_url: str
    planned_output_path: str
    effective_options: dict[str, Any]


class CaptureSuccess(BaseModel):
    ok: bool = True
    backend: str = "webcapture"
    requested_url: str
    final_url: str
    title: str | None = None
    output: OutputFile
    duration_ms: int
    navigation_status: NavigationStatus
