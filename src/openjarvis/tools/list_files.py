"""Read-only directory listing tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_RESULTS = 200


@ToolRegistry.register("list_files")
class ListFilesTool(BaseTool):
    """List ordinary directory entries without granting command execution."""

    tool_id = "list_files"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_files",
            description=(
                "List files and folders in a directory. This is read-only and does not "
                "require shell_exec. Use it to locate a file before calling file_read."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute directory path to list.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional filename glob such as '*.md'.",
                    },
                },
                "required": ["path"],
            },
            category="filesystem",
            requires_confirmation=False,
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        raw_path = str(params.get("path", "")).strip()
        if not raw_path:
            return ToolResult(
                tool_name="list_files", content="No path provided.", success=False
            )
        directory = Path(raw_path).expanduser()
        if not directory.exists():
            return ToolResult(
                tool_name="list_files",
                content=f"Directory not found: {directory}",
                success=False,
            )
        if not directory.is_dir():
            return ToolResult(
                tool_name="list_files",
                content=f"Not a directory: {directory}",
                success=False,
            )

        pattern = str(params.get("pattern") or "*")
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            return ToolResult(
                tool_name="list_files",
                content="Invalid pattern: use a filename glob without parent paths.",
                success=False,
            )
        try:
            entries = sorted(
                directory.glob(pattern),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
        except (OSError, ValueError) as exc:
            return ToolResult(
                tool_name="list_files", content=f"List error: {exc}", success=False
            )

        lines: list[str] = []
        for item in entries[:_MAX_RESULTS]:
            kind = "DIR " if item.is_dir() else "FILE"
            try:
                size = "" if item.is_dir() else f" ({item.stat().st_size} bytes)"
            except OSError:
                size = ""
            lines.append(f"{kind} {item.resolve()}{size}")
        if len(entries) > _MAX_RESULTS:
            lines.append(f"... {len(entries) - _MAX_RESULTS} more entries omitted")
        return ToolResult(
            tool_name="list_files",
            content="\n".join(lines) if lines else "No matching entries.",
            success=True,
            metadata={"path": str(directory.resolve()), "count": len(entries)},
        )


__all__ = ["ListFilesTool"]
