"""FastMCP file entrypoint for CLI tools that load a Python file path."""

from toolhub.mcp_server import http_main, main, mcp

__all__ = ["mcp", "main", "http_main"]


if __name__ == "__main__":
    main()
