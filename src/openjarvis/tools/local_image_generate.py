"""Generate images using the loopback diffusion worker and resource scheduler."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.core.local_images import generate_image
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("local_image_generate")
class LocalImageGenerateTool(BaseTool):
    tool_id = "local_image_generate"
    is_local = True

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description="Generate an image locally with automatic GPU/CPU scheduling. Use a detailed English visual prompt. Returns a Markdown image link and saved file path.",
            category="media", required_capabilities=["fs:write"],
            timeout_seconds=900,
            parameters={"type": "object", "properties": {
                "prompt": {"type": "string", "description": "English description of subject, scene, style, light and composition."},
                "negative_prompt": {"type": "string"},
                "width": {"type": "integer", "description": "Default 512; multiples of 64, 256 through 768."},
                "height": {"type": "integer", "description": "Default 512; multiples of 64, 256 through 768."},
                "steps": {"type": "integer", "description": "LCM steps, default 4, from 1 through 8."},
                "seed": {"type": "integer", "description": "Reproducible seed; default 42."},
            }, "required": ["prompt"]},
        )

    def execute(self, **params: Any):
        allowed = {"prompt", "negative_prompt", "width", "height", "steps", "seed"}
        try:
            result = generate_image(**{k: v for k, v in params.items() if k in allowed})
            content = f"![本地生成图片]({result['url']})\n\n" + json.dumps(result, ensure_ascii=False)
            return ToolResult(tool_name=self.tool_id, success=True, content=content)
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id, success=False, content=str(exc))
