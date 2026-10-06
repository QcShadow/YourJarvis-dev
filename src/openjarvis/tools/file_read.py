"""File read tool — read file contents with path validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Maximum file size to read (1 MB)
_MAX_SIZE_BYTES = 1_048_576


@ToolRegistry.register("file_read")
class FileReadTool(BaseTool):
    """Read file contents with optional directory restrictions."""

    tool_id = "file_read"

    def __init__(
        self,
        allowed_dirs: Optional[List[str]] = None,
    ) -> None:
        self._allowed_dirs = [Path(d).resolve() for d in (allowed_dirs or [])]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_read",
            description=("Read the contents of a file. Returns the text content."),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": ("Max lines to return (default: 400, 0 = all)."),
                    },
                    "start_line": {
                        "type": "integer",
                        "description": (
                            "One-based line to start reading from (default: 1)."
                        ),
                    },
                },
                "required": ["path"],
            },
            category="filesystem",
        )

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is within allowed directories."""
        if not self._allowed_dirs:
            return True
        resolved = path.resolve()
        return any(
            resolved == d or resolved.is_relative_to(d) for d in self._allowed_dirs
        )

    def execute(self, **params: Any) -> ToolResult:
        file_path = params.get("path", "")
        if not file_path:
            return ToolResult(
                tool_name="file_read",
                content="No path provided.",
                success=False,
            )
        path = Path(file_path)
        # Block sensitive files (secrets, credentials, keys)
        from openjarvis.security.file_policy import is_sensitive_file

        if is_sensitive_file(path):
            return ToolResult(
                tool_name="file_read",
                content=f"Access denied: {file_path} is a sensitive file.",
                success=False,
            )
        if not path.exists():
            return ToolResult(
                tool_name="file_read",
                content=f"File not found: {file_path}",
                success=False,
            )
        if not path.is_file():
            return ToolResult(
                tool_name="file_read",
                content=f"Not a file: {file_path}",
                success=False,
            )
        if not self._is_path_allowed(path):
            return ToolResult(
                tool_name="file_read",
                content=f"Access denied: {file_path} is outside allowed directories.",
                success=False,
            )
        # Check size
        try:
            size = path.stat().st_size
        except OSError as exc:
            return ToolResult(
                tool_name="file_read",
                content=f"Cannot stat file: {exc}",
                success=False,
            )
        if size > _MAX_SIZE_BYTES:
            return ToolResult(
                tool_name="file_read",
                content=f"File too large: {size} bytes (max {_MAX_SIZE_BYTES}).",
                success=False,
            )
        try:
            from openjarvis._rust_bridge import get_rust_module

            _rust = get_rust_module()
            text = _rust.FileReadTool().execute(str(path))
        except ImportError:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(
                tool_name="file_read",
                content=f"Read error: {exc}",
                success=False,
            )
        lines = text.splitlines(keepends=True)
        try:
            start_line = max(1, int(params.get("start_line", 1)))
        except (TypeError, ValueError):
            start_line = 1
        try:
            max_lines = int(params.get("max_lines", 400))
        except (TypeError, ValueError):
            max_lines = 400
        start_index = start_line - 1
        selected = (
            lines[start_index:]
            if max_lines <= 0
            else lines[start_index : start_index + max_lines]
        )
        body = "".join(selected)
        end_line = start_index + len(selected)
        truncated = end_line < len(lines)
        header = (
            f"File: {path.resolve()}\n"
            f"Size: {size} bytes; total lines: {len(lines)}; "
            f"showing lines {start_line}-{end_line}"
        )
        if truncated:
            header += f" (truncated; continue with start_line={end_line + 1})"
        text = f"{header}\n\n{body}"
        return ToolResult(
            tool_name="file_read",
            content=text,
            success=True,
            metadata={
                "path": str(path.resolve()),
                "size_bytes": size,
                "start_line": start_line,
                "end_line": end_line,
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )


__all__ = ["FileReadTool"]
