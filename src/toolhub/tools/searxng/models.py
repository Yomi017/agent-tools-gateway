from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator


SUPPORTED_SAFE_SEARCH = frozenset({"off", "moderate", "strict"})
SUPPORTED_TIME_RANGES = frozenset({"day", "month", "year"})
SAFE_SEARCH_TO_UPSTREAM = {
    "off": 0,
    "moderate": 1,
    "strict": 2,
}


def normalize_safe_search(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_SAFE_SEARCH:
        raise ValueError(
            f"safe_search must be one of {', '.join(sorted(SUPPORTED_SAFE_SEARCH))}"
        )
    return normalized


def normalize_time_range(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_TIME_RANGES:
        raise ValueError(
            f"time_range must be one of {', '.join(sorted(SUPPORTED_TIME_RANGES))}"
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


def _require_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return value


class SearXNGSearchRequest(BaseModel):
    query: str
    limit: int | None = None
    language: str | None = None
    time_range: str | None = None
    safe_search: str | None = None
    page: int | None = None

    @field_validator("query", mode="before")
    @classmethod
    def _validate_query(cls, value: Any) -> str:
        query = _require_string(value, "query").strip()
        if not query:
            raise ValueError("query must not be empty")
        return query

    @field_validator("language", mode="before")
    @classmethod
    def _validate_language(cls, value: Any) -> str | None:
        return _require_optional_string(value, "language")

    @field_validator("time_range", mode="before")
    @classmethod
    def _validate_time_range(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_time_range(_require_string(value, "time_range"))

    @field_validator("safe_search", mode="before")
    @classmethod
    def _validate_safe_search(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_safe_search(_require_string(value, "safe_search"))

    @field_validator("limit", "page", mode="before")
    @classmethod
    def _validate_positive_ints(cls, value: Any, info) -> int | None:
        return _require_optional_int(value, info.field_name)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    engine: str | None = None
    position: int
    published_date: str | None = None
    thumbnail_url: str | None = None


class SearchWarnings(BaseModel):
    unresponsive_engines: list[str]


class SearXNGSearchSuccess(BaseModel):
    ok: bool = True
    backend: str = "searxng"
    query: str
    result_count: int
    results: list[SearchResult]
    effective_options: dict[str, Any]
    warnings: SearchWarnings | None = None
    duration_ms: int
