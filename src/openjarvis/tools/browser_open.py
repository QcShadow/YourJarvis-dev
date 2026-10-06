"""Open a normal web URL in the user's default browser."""

from __future__ import annotations

import webbrowser
from typing import Any
from urllib.parse import urlsplit

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("browser_open")
class BrowserOpenTool(BaseTool):
    """Open an HTTP(S) page without exposing general shell execution."""

    tool_id = "browser_open"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_open",
            description=(
                "Open the user's default browser, optionally at an http:// or "
                "https:// URL. Omit url to open the browser start page. Use this "
                "instead of shell_exec."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Complete http:// or https:// URL to open.",
                    }
                },
                "required": [],
            },
            category="system",
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        url = str(params.get("url", "")).strip() or "https://www.bing.com/"
        if len(url) > 4096:
            return ToolResult(
                tool_name="browser_open", content="Invalid URL.", success=False
            )
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ToolResult(
                tool_name="browser_open",
                content="Only complete http:// and https:// URLs are allowed.",
                success=False,
            )
        if parsed.username or parsed.password:
            return ToolResult(
                tool_name="browser_open",
                content="URLs containing embedded credentials are not allowed.",
                success=False,
            )
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            return ToolResult(
                tool_name="browser_open",
                content=f"Could not open browser: {exc}",
                success=False,
            )
        if not opened:
            return ToolResult(
                tool_name="browser_open",
                content=f"The system browser did not accept the URL: {url}",
                success=False,
            )
        return ToolResult(
            tool_name="browser_open",
            content=f"Opened in the default browser: {url}",
            success=True,
            metadata={"url": url},
        )


__all__ = ["BrowserOpenTool"]
