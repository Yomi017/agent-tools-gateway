from __future__ import annotations

from typing import Any

import uvicorn
from fastmcp import FastMCP

from .config import get_settings
from .service import (
    convert_batch_payload,
    convert_file_payload,
    health_payload,
    list_targets_payload,
)

mcp = FastMCP("toolhub")


@mcp.tool
async def toolhub_health() -> dict[str, Any]:
    """Check Agent Tools Gateway and ConvertX reachability."""
    return await health_payload()


@mcp.tool
async def list_conversion_targets(input_format: str | None = None) -> dict[str, Any]:
    """List ConvertX output formats, optionally filtered by one input extension."""
    return await list_targets_payload(input_format)


@mcp.tool
async def convert_file(
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Convert one local file through ConvertX and return local output paths."""
    return await convert_file_payload(
        input_path=input_path,
        output_format=output_format,
        output_dir=output_dir,
        converter=converter,
        overwrite=overwrite,
    )


@mcp.tool
async def convert_batch(
    input_paths: list[str],
    output_format: str,
    output_dir: str | None = None,
    converter: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Convert multiple local files with the same extension through ConvertX."""
    return await convert_batch_payload(
        input_paths=input_paths,
        output_format=output_format,
        output_dir=output_dir,
        converter=converter,
        overwrite=overwrite,
    )


def main() -> None:
    mcp.run()


def http_main() -> None:
    settings = get_settings()
    # Use uvicorn directly for the HTTP transport. This avoids FastMCP CLI
    # process-management quirks while still serving the FastMCP ASGI app at /mcp.
    app = mcp.http_app(transport="http", path="/mcp")
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
