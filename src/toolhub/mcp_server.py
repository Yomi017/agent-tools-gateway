from __future__ import annotations

from typing import Any, Awaitable, Callable

import uvicorn
from fastmcp import FastMCP
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .registry import get_enabled_backends
from .service import health_payload


Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def create_mcp(settings: Settings | None = None) -> FastMCP:
    runtime = settings or get_settings()
    mcp = FastMCP("toolhub")

    @mcp.tool(name="toolhub_health")
    async def toolhub_health() -> dict[str, Any]:
        """Check Agent Tools Gateway and enabled backends."""
        return await health_payload(runtime)

    for backend in get_enabled_backends(runtime):
        backend.register_mcp(mcp, runtime)

    return mcp


mcp = create_mcp()


def _http_auth_app(app: AsgiApp, token: str | None) -> AsgiApp:
    if not token:
        return app

    async def _wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return

        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        if headers.get("authorization") != f"Bearer {token}":
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return

        await app(scope, receive, send)

    return _wrapped


def create_http_app(settings: Settings | None = None) -> AsgiApp:
    runtime = settings or get_settings()
    app = create_mcp(runtime).http_app(transport="streamable-http", path="/mcp")
    return _http_auth_app(app, runtime.auth_token)


def main() -> None:
    create_mcp(get_settings()).run()


def http_main() -> None:
    settings = get_settings()
    app = create_http_app(settings)
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
