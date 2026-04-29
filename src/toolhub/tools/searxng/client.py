from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ...config import SearXNGRuntimeSettings
from ...errors import UpstreamError
from .models import SAFE_SEARCH_TO_UPSTREAM


class SearXNGClient:
    def __init__(
        self,
        settings: SearXNGRuntimeSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.settings.request_timeout_seconds,
            connect=self.settings.connect_timeout_seconds,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            headers={"Accept": "application/json"},
            timeout=self._timeout(),
            transport=self._transport,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get("/healthz")
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }

        result: dict[str, Any] = {
            "reachable": 200 <= response.status_code < 300,
            "base_url": self.settings.base_url,
            "status_code": response.status_code,
        }
        body_preview = response.text[:500]
        if body_preview:
            result["body_preview"] = body_preview
        if not result["reachable"]:
            return result

        try:
            async with self._client() as client:
                config_response = await client.get("/config")
        except httpx.HTTPError as exc:
            result["config_error"] = str(exc)
            return result

        config_payload = self._maybe_json_dict(config_response)
        if 200 <= config_response.status_code < 300 and config_payload is not None:
            result["config_status_code"] = config_response.status_code
            result["instance_name"] = self._instance_name(config_payload)
            result["categories"] = self._categories(config_payload)
            result["enabled_engines"] = self._enabled_engines(config_payload)
            return result

        result["config_status_code"] = config_response.status_code
        result["config_body_preview"] = self._response_preview(
            config_response,
            parsed_payload=config_payload,
        )
        return result

    async def search(
        self,
        *,
        query: str,
        language: str,
        safe_search: str,
        page: int,
        time_range: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": SAFE_SEARCH_TO_UPSTREAM[safe_search],
            "pageno": page,
        }
        if time_range:
            params["time_range"] = time_range

        start = time.perf_counter()
        async with self._client() as client:
            response = await client.get("/search", params=params)
        payload = self._json_response(response, "search SearXNG")
        duration_ms = int((time.perf_counter() - start) * 1000)
        return payload, duration_ms

    @staticmethod
    def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code == 403:
            raise UpstreamError(
                "SearXNG rejected JSON search results. Ensure search.formats includes json.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"SearXNG failed to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                f"SearXNG returned non-JSON while trying to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamError(
                f"SearXNG returned an unexpected JSON payload while trying to {action}.",
                details={"status_code": response.status_code, "payload_type": type(payload).__name__},
            )
        return payload

    @staticmethod
    def _maybe_json_dict(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _response_preview(
        response: httpx.Response,
        *,
        parsed_payload: dict[str, Any] | None = None,
    ) -> str:
        if parsed_payload is not None:
            return json.dumps(parsed_payload, ensure_ascii=False)[:500]
        return response.text[:500]

    @staticmethod
    def _instance_name(payload: dict[str, Any]) -> str | None:
        if isinstance(payload.get("instance_name"), str):
            return payload["instance_name"]
        general = payload.get("general")
        if isinstance(general, dict) and isinstance(general.get("instance_name"), str):
            return general["instance_name"]
        brand = payload.get("brand")
        if isinstance(brand, dict) and isinstance(brand.get("name"), str):
            return brand["name"]
        return None

    @staticmethod
    def _categories(payload: dict[str, Any]) -> list[str]:
        candidates = payload.get("categories") or payload.get("categories_as_tabs")
        if isinstance(candidates, list):
            return [str(item) for item in candidates if str(item).strip()]
        return []

    @staticmethod
    def _enabled_engines(payload: dict[str, Any]) -> list[str]:
        engines = payload.get("engines")
        if not isinstance(engines, list):
            return []
        names: list[str] = []
        for item in engines:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name)
                    continue
            if isinstance(item, str) and item.strip():
                names.append(item)
        return names
