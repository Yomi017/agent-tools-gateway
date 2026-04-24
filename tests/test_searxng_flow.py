from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from toolhub.api import create_app
from toolhub.backends.searxng import SearXNGClient
from toolhub.config import Settings
from toolhub.errors import UpstreamError
from toolhub.tools.searxng.backend import search


@pytest.mark.asyncio
async def test_searxng_client_health_reads_config(searxng_settings) -> None:
    runtime = searxng_settings.searxng()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, text="OK")
        if request.url.path == "/config":
            return httpx.Response(
                200,
                json={
                    "general": {"instance_name": "Toolhub Search"},
                    "categories": ["general", "news"],
                    "engines": [{"name": "duckduckgo"}, {"name": "brave"}],
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    client = SearXNGClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert payload["reachable"] is True
    assert payload["instance_name"] == "Toolhub Search"
    assert payload["categories"] == ["general", "news"]
    assert payload["enabled_engines"] == ["duckduckgo", "brave"]


@pytest.mark.asyncio
async def test_searxng_client_health_keeps_reachable_when_config_fails(searxng_settings) -> None:
    runtime = searxng_settings.searxng()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, text="OK")
        if request.url.path == "/config":
            return httpx.Response(404, text="Not Found")
        raise AssertionError(f"Unexpected path: {request.url.path}")

    client = SearXNGClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert payload["reachable"] is True
    assert payload["config_status_code"] == 404
    assert payload["config_body_preview"] == "Not Found"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 500])
async def test_searxng_client_health_rejects_non_2xx_health(
    searxng_settings,
    status_code: int,
) -> None:
    runtime = searxng_settings.searxng()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(status_code, text="bad health")

    client = SearXNGClient(runtime, transport=httpx.MockTransport(handler))

    payload = await client.health()

    assert payload["reachable"] is False
    assert payload["status_code"] == status_code


@pytest.mark.asyncio
async def test_searxng_client_search_rejects_missing_json_format(searxng_settings) -> None:
    runtime = searxng_settings.searxng()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(403, text="disabled response format: json")

    client = SearXNGClient(runtime, transport=httpx.MockTransport(handler))

    with pytest.raises(UpstreamError, match="Ensure search.formats includes json"):
        await client.search(
            query="example",
            language="auto",
            safe_search="moderate",
            page=1,
        )


@pytest.mark.asyncio
async def test_searxng_backend_normalizes_results_and_applies_limit(
    searxng_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, _runtime) -> None:
            pass

        async def search(self, **kwargs):
            assert kwargs == {
                "query": "openai",
                "language": "zh-CN",
                "safe_search": "strict",
                "page": 2,
                "time_range": "day",
            }
            return (
                {
                    "results": [
                        {
                            "title": "Result 1",
                            "url": "https://example.com/1",
                            "content": "Snippet 1",
                            "engine": "brave",
                            "publishedDate": "2026-04-24",
                            "thumbnail": "https://example.com/1.png",
                        },
                        {
                            "title": "",
                            "url": "https://example.com/2",
                            "content": "Snippet 2",
                            "engines": ["duckduckgo", "brave"],
                        },
                        {
                            "title": "Skipped",
                            "content": "Missing url",
                        },
                    ],
                    "unresponsive_engines": [["duckduckgo", "timeout"]],
                },
                19,
            )

    monkeypatch.setattr("toolhub.tools.searxng.backend.SearXNGClient", FakeClient)

    payload = await search(
        query="openai",
        limit=2,
        language="zh-CN",
        time_range="day",
        safe_search="strict",
        page=2,
        settings=searxng_settings,
    )

    assert payload.result_count == 2
    assert payload.duration_ms == 19
    assert payload.results[0].title == "Result 1"
    assert payload.results[0].published_date == "2026-04-24"
    assert payload.results[1].title == "https://example.com/2"
    assert payload.results[1].engine == "duckduckgo"
    assert payload.warnings is not None
    assert payload.warnings.unresponsive_engines == ["duckduckgo: timeout"]


def test_searxng_search_route_validates_payload_types() -> None:
    app = create_app(Settings(backends={"searxng": {"enabled": True}}))
    client = TestClient(app)

    response = client.post(
        "/v1/searxng/search",
        json={"query": 123, "limit": "bad"},
    )

    assert response.status_code == 422
