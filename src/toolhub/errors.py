from __future__ import annotations

from typing import Any


class ToolhubError(Exception):
    """Base error that can be returned directly to agents."""

    code = "toolhub_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


def error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ToolhubError):
        return exc.to_payload()
    return ToolhubError(
        "Unexpected toolhub failure.",
        code="internal_error",
        details={"type": type(exc).__name__, "message": str(exc)},
    ).to_payload()


class PathNotAllowedError(ToolhubError):
    code = "path_not_allowed"


class FileTooLargeError(ToolhubError):
    code = "file_too_large"


class FormatNotSupportedError(ToolhubError):
    code = "format_not_supported"


class ConversionTimeoutError(ToolhubError):
    code = "conversion_timeout"


class UpstreamError(ToolhubError):
    code = "upstream_error"


class UnsafeArchiveError(ToolhubError):
    code = "unsafe_archive"
