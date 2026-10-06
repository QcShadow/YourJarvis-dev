"""Read-only local system time tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("system_time")
class SystemTimeTool(BaseTool):
    """Return the host clock without invoking a shell or the network."""

    tool_id = "system_time"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_time",
            description=(
                "Return the computer's current local date, time, UTC offset, and "
                "timezone. Always use this for questions about the current time or "
                "date; do not use web search or shell commands."
            ),
            parameters={"type": "object", "properties": {}},
            category="system",
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        now = datetime.now().astimezone()
        timezone_name = now.tzname() or "local"
        return ToolResult(
            tool_name="system_time",
            content=(
                f"Local system time: {now:%Y-%m-%d %H:%M:%S}; "
                f"timezone: {timezone_name}; UTC offset: {now:%z}"
            ),
            success=True,
            metadata={"iso8601": now.isoformat(), "timezone": timezone_name},
        )


__all__ = ["SystemTimeTool"]
