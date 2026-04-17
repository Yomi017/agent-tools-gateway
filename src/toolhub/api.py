from __future__ import annotations

from typing import Annotated, Callable

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .errors import error_payload
from .registry import get_enabled_backends
from .service import health


def _auth_dependency(token: str | None) -> Callable[[Annotated[str | None, Header()]], None]:
    def _auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if not token:
            return
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")

    return _auth


def _json(payload: object) -> JSONResponse:
    if hasattr(payload, "model_dump"):
        return JSONResponse(payload.model_dump())
    return JSONResponse(payload)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()
    auth = _auth_dependency(runtime.auth_token)
    app = FastAPI(title="Agent Tools Gateway", version="0.1.0")

    @app.get("/health")
    async def health_route(_authorized: None = Depends(auth)) -> JSONResponse:
        try:
            return _json(await health(runtime))
        except Exception as exc:
            return _json(error_payload(exc))

    for backend in get_enabled_backends(runtime):
        backend.register_api(app, auth, _json, runtime)

    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "toolhub.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
