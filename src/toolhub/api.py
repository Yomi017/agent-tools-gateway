from __future__ import annotations

from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .config import get_settings
from .models import BatchConvertRequest, ConvertRequest
from .service import (
    convert_batch,
    convert_file,
    error_payload,
    health,
    list_conversion_targets,
)

app = FastAPI(title="Agent Tools Gateway", version="0.1.0")


def _auth(authorization: Annotated[str | None, Header()] = None) -> None:
    token = get_settings().auth_token
    if not token:
        return
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _json(payload: object) -> JSONResponse:
    if hasattr(payload, "model_dump"):
        return JSONResponse(payload.model_dump())
    return JSONResponse(payload)


@app.get("/health")
async def health_route(_authorized: None = Depends(_auth)) -> JSONResponse:
    try:
        return _json(await health())
    except Exception as exc:
        return _json(error_payload(exc))


@app.get("/v1/convertx/targets")
async def targets_route(
    input_format: str | None = None,
    _authorized: None = Depends(_auth),
) -> JSONResponse:
    try:
        return _json(await list_conversion_targets(input_format))
    except Exception as exc:
        return _json(error_payload(exc))


@app.post("/v1/convertx/convert")
async def convert_route(
    request: ConvertRequest,
    _authorized: None = Depends(_auth),
) -> JSONResponse:
    try:
        result = await convert_file(
            input_path=request.input_path,
            output_format=request.output_format,
            output_dir=request.output_dir,
            converter=request.converter,
            overwrite=request.overwrite,
        )
        return _json(result)
    except Exception as exc:
        return _json(error_payload(exc))


@app.post("/v1/convertx/convert-batch")
async def convert_batch_route(
    request: BatchConvertRequest,
    _authorized: None = Depends(_auth),
) -> JSONResponse:
    try:
        result = await convert_batch(
            input_paths=request.input_paths,
            output_format=request.output_format,
            output_dir=request.output_dir,
            converter=request.converter,
            overwrite=request.overwrite,
        )
        return _json(result)
    except Exception as exc:
        return _json(error_payload(exc))


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
