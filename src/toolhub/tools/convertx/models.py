from __future__ import annotations

from pydantic import BaseModel

from ...models import OutputFile


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


class TargetCandidate(BaseModel):
    target: str
    converter: str
    value: str


class TargetsSuccess(BaseModel):
    ok: bool = True
    backend: str = "convertx"
    input_format: str | None = None
    targets: list[TargetCandidate]
