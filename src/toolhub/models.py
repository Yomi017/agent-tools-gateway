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


class ErrorResponse(BaseModel):
    ok: bool = False
    error: ErrorDetail


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "agent-tools-gateway"
    backends: dict[str, Any]
