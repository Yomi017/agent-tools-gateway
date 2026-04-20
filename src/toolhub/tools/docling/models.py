from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from ...models import OutputFile


SUPPORTED_DOCLING_OUTPUT_FORMATS = frozenset({"md", "json", "html", "text", "doctags", "vtt"})
DOCLING_OUTPUT_EXTENSIONS = {
    "md": "md",
    "json": "json",
    "html": "html",
    "text": "txt",
    "doctags": "doctags",
    "vtt": "vtt",
}


def normalize_docling_output_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if normalized not in SUPPORTED_DOCLING_OUTPUT_FORMATS:
        raise ValueError(
            f"output_format must be one of {', '.join(sorted(SUPPORTED_DOCLING_OUTPUT_FORMATS))}"
        )
    return normalized


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _require_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


class DoclingRequest(BaseModel):
    input_path: str
    output_format: str
    output_dir: str | None = None
    filename_stem: str | None = None
    overwrite: bool = False
    do_ocr: bool | None = None
    force_ocr: bool | None = None
    ocr_engine: str | None = None
    pdf_backend: str | None = None
    table_mode: str | None = None
    image_export_mode: str | None = None
    include_images: bool | None = None

    @field_validator("input_path", "output_dir", "filename_stem", mode="before")
    @classmethod
    def _validate_strings(cls, value: Any, info) -> str | None:
        return _require_optional_string(value, info.field_name)

    @field_validator("output_format", mode="before")
    @classmethod
    def _normalize_output_format(cls, value: Any) -> str:
        return normalize_docling_output_format(_require_string(value, "output_format"))

    @field_validator(
        "ocr_engine",
        "pdf_backend",
        "table_mode",
        "image_export_mode",
        mode="before",
    )
    @classmethod
    def _validate_optional_strings(cls, value: Any, info) -> str | None:
        return _require_optional_string(value, info.field_name)

    @field_validator("do_ocr", "force_ocr", "include_images", mode="before")
    @classmethod
    def _validate_optional_booleans(cls, value: Any, info) -> bool | None:
        return _require_optional_bool(value, info.field_name)


class DoclingCheckSuccess(BaseModel):
    ok: bool = True
    backend: str = "docling"
    check: bool = True
    input_path: str
    planned_output_path: str
    effective_options: dict[str, Any]


class DoclingConvertSuccess(BaseModel):
    ok: bool = True
    backend: str = "docling"
    input_path: str
    output_format: str
    task_id: str
    output: OutputFile
    duration_ms: int
