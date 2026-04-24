from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from ...config import SearXNGRuntimeSettings, Settings, get_settings
from ...errors import error_payload
from .client import SearXNGClient
from .models import SearXNGSearchRequest, SearXNGSearchSuccess, SearchResult, SearchWarnings


backend_key = "searxng"


def _runtime(settings: Settings | None = None) -> SearXNGRuntimeSettings:
    return (settings or get_settings()).searxng()


def _effective_options(
    *,
    limit: int,
    language: str,
    time_range: str | None,
    safe_search: str,
    page: int,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "limit": limit,
        "language": language,
        "safe_search": safe_search,
        "page": page,
    }
    if time_range is not None:
        options["time_range"] = time_range
    return options


def _normalize_engine(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item
    return None


def _normalize_warning_entry(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        for key in ("name", "engine", "message", "error"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        if parts:
            return ": ".join(parts)
    return None


def _normalize_result(item: dict[str, Any], position: int) -> SearchResult | None:
    raw_url = item.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    title = item.get("title")
    normalized_title = title.strip() if isinstance(title, str) and title.strip() else raw_url
    snippet = ""
    for key in ("content", "snippet", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            snippet = value.strip()
            break

    published_date = None
    for key in ("publishedDate", "published_date", "published"):
        value = item.get(key)
        if value is not None:
            published_date = str(value)
            break

    thumbnail_url = None
    for key in ("thumbnail", "thumbnail_url", "thumbnail_src", "img_src"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            thumbnail_url = value
            break

    return SearchResult(
        title=normalized_title,
        url=raw_url,
        snippet=snippet,
        engine=_normalize_engine(item.get("engine") or item.get("engines")),
        position=position,
        published_date=published_date,
        thumbnail_url=thumbnail_url,
    )


def _normalize_results(payload: dict[str, Any], *, limit: int) -> list[SearchResult]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_result(item, len(results) + 1)
        if normalized is None:
            continue
        results.append(normalized)
        if len(results) >= limit:
            break
    return results


def _warnings(payload: dict[str, Any]) -> SearchWarnings | None:
    raw = payload.get("unresponsive_engines")
    if not isinstance(raw, list):
        return None
    normalized = [entry for item in raw if (entry := _normalize_warning_entry(item))]
    if not normalized:
        return None
    return SearchWarnings(unresponsive_engines=normalized)


async def health(settings: Settings | None = None) -> dict[str, Any]:
    runtime = _runtime(settings)
    client = SearXNGClient(runtime)
    return await client.health()


async def search(
    *,
    query: str,
    limit: int | None = None,
    language: str | None = None,
    time_range: str | None = None,
    safe_search: str | None = None,
    page: int | None = None,
    settings: Settings | None = None,
) -> SearXNGSearchSuccess:
    request = SearXNGSearchRequest.model_validate(
        {
            "query": query,
            "limit": limit,
            "language": language,
            "time_range": time_range,
            "safe_search": safe_search,
            "page": page,
        }
    )
    runtime = _runtime(settings)
    effective_limit = min(request.limit or runtime.default_limit, runtime.max_limit)
    effective_language = (
        (request.language or runtime.default_language).strip() or runtime.default_language
    )
    effective_safe_search = request.safe_search or runtime.default_safe_search
    effective_page = request.page or 1

    client = SearXNGClient(runtime)
    payload, duration_ms = await client.search(
        query=request.query,
        language=effective_language,
        safe_search=effective_safe_search,
        page=effective_page,
        time_range=request.time_range,
    )
    results = _normalize_results(payload, limit=effective_limit)
    warnings = _warnings(payload)
    response = SearXNGSearchSuccess(
        query=request.query,
        result_count=len(results),
        results=results,
        effective_options=_effective_options(
            limit=effective_limit,
            language=effective_language,
            time_range=request.time_range,
            safe_search=effective_safe_search,
            page=effective_page,
        ),
        warnings=warnings,
        duration_ms=duration_ms,
    )
    return response


async def health_payload(settings: Settings | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "backend": backend_key, "health": await health(settings)}
    except Exception as exc:
        return error_payload(exc)


async def search_payload(
    *,
    query: str,
    limit: int | None = None,
    language: str | None = None,
    time_range: str | None = None,
    safe_search: str | None = None,
    page: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        payload = await search(
            query=query,
            limit=limit,
            language=language,
            time_range=time_range,
            safe_search=safe_search,
            page=page,
            settings=settings,
        )
        return payload.model_dump()
    except Exception as exc:
        return error_payload(exc)


class SearXNGBackend:
    key = backend_key

    def is_enabled(self, settings: Settings) -> bool:
        return settings.searxng().enabled

    async def health(self, settings: Settings) -> dict[str, Any]:
        return await health(settings)

    def register_api(
        self,
        app: FastAPI,
        auth_dependency: Callable[..., None],
        json_response: Callable[[object], JSONResponse],
        settings: Settings,
    ) -> None:
        router = APIRouter(prefix="/v1/searxng", tags=["searxng"])

        @router.post("/search")
        async def search_route(
            request: SearXNGSearchRequest,
            _authorized: None = Depends(auth_dependency),
        ) -> JSONResponse:
            return json_response(
                await search_payload(
                    query=request.query,
                    limit=request.limit,
                    language=request.language,
                    time_range=request.time_range,
                    safe_search=request.safe_search,
                    page=request.page,
                    settings=settings,
                )
            )

        app.include_router(router)

    def register_mcp(self, mcp: FastMCP, settings: Settings) -> None:
        @mcp.tool(name="searxng_health")
        async def searxng_health() -> dict[str, Any]:
            """Check SearXNG reachability for the search backend."""
            return await health_payload(settings)

        @mcp.tool(name="searxng_search")
        async def searxng_search(
            query: str,
            limit: int | None = None,
            language: str | None = None,
            time_range: str | None = None,
            safe_search: str | None = None,
            page: int | None = None,
        ) -> dict[str, Any]:
            """Search the web through the local SearXNG backend."""
            return await search_payload(
                query=query,
                limit=limit,
                language=language,
                time_range=time_range,
                safe_search=safe_search,
                page=page,
                settings=settings,
            )


BACKEND = SearXNGBackend()
