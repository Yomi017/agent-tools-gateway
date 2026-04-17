from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class OutputFile(BaseModel):
    path: str
    filename: str


class ConvertRequest(BaseModel):
    input_path: str
    output_format: str
    output_dir: str | None = None
    converter: str | None = None
    overwrite: bool = False


class BatchConvertRequest(BaseModel):
    input_paths: list[str]
    output_format: str
    output_dir: str | None = None
    converter: str | None = None
    overwrite: bool = False


class ConvertSuccess(BaseModel):
    ok: bool = True
    backend: str = "convertx"
    job_id: str
    outputs: list[OutputFile]
    duration_ms: int


class ErrorResponse(BaseModel):
    ok: bool = False
    error: ErrorDetail


class TargetCandidate(BaseModel):
    target: str
    converter: str
    value: str


class TargetsSuccess(BaseModel):
    ok: bool = True
    backend: str = "convertx"
    input_format: str | None = None
    targets: list[TargetCandidate]


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "agent-tools-gateway"
    backends: dict[str, Any]
