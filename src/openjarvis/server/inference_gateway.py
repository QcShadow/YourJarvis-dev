"""OpenAI-compatible inference for complete clients; never executes host tools."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import aclosing
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.core.types import Message, Role, ToolCall


class GatewayMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default="", max_length=100000)
    name: str | None = Field(default=None, max_length=256)
    tool_call_id: str | None = Field(default=None, max_length=256)
    tool_calls: list[dict] | None = Field(default=None, max_length=64)
    images: list[str] | None = Field(default=None, max_length=8)


class GatewayCompletion(BaseModel):
    model: str = Field(max_length=256)
    messages: list[GatewayMessage] = Field(min_length=1, max_length=128)
    tools: list[dict] | None = Field(default=None, max_length=64)
    stream: bool = False
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=4096)


def install_inference_routes(
    app,
    *,
    engine,
    model,
    authenticated,
    admit,
    response_class,
    inference_seconds,
    num_ctx,
):
    @app.get("/v1/models")
    async def models(member: str = Depends(authenticated)):
        return {
            "object": "list",
            "data": [
                {
                    "id": "host-model",
                    "object": "model",
                    "owned_by": "jarvis-host",
                    "name": model,
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def completion(
        body: GatewayCompletion,
        request: Request,
        member: str = Depends(authenticated),
    ):
        if body.model not in {model, "host-model"}:
            raise HTTPException(404, "Only the host-selected model is available.")
        # Conversion happens before admission, so malformed tool history cannot
        # leave a queue slot occupied. Schemas are forwarded as data only.
        try:
            messages = [
                Message(
                    role=Role(m.role),
                    content=m.content or "",
                    name=m.name,
                    tool_call_id=m.tool_call_id,
                    images=m.images,
                    tool_calls=[
                        ToolCall(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=tc["function"].get("arguments", "{}"),
                        )
                        for tc in m.tool_calls
                    ]
                    if m.tool_calls
                    else None,
                )
                for m in body.messages
            ]
        except (KeyError, TypeError) as exc:
            raise HTTPException(422, "Invalid tool-call history.") from exc
        release = await admit(member)
        ident, created = "chatcmpl-" + uuid.uuid4().hex[:12], int(time.time())

        async def events():
            kwargs = {"tools": body.tools} if body.tools else {}
            upstream = engine.stream_full(
                messages,
                model=model,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                num_ctx=num_ctx,
                **kwargs,
            )
            async with aclosing(upstream):
                deadline = time.monotonic() + inference_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        chunk = await asyncio.wait_for(anext(upstream), remaining)
                    except StopAsyncIteration:
                        return
                    yield chunk

        if body.stream:

            async def stream():
                try:
                    async with aclosing(events()) as upstream:
                        async for chunk in upstream:
                            if await request.is_disconnected():
                                return
                            delta = {}
                            if chunk.content:
                                delta["content"] = chunk.content
                            if chunk.tool_calls:
                                delta["tool_calls"] = chunk.tool_calls
                            value = {
                                "id": ident,
                                "created": created,
                                "model": model,
                                "object": "chat.completion.chunk",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": delta,
                                        "finish_reason": chunk.finish_reason,
                                    }
                                ],
                            }
                            if chunk.usage:
                                value["usage"] = chunk.usage
                            yield (
                                "data: "
                                + json.dumps(value, ensure_ascii=False)
                                + "\n\n"
                            )
                    yield "data: [DONE]\n\n"
                except Exception:
                    yield (
                        'data: {"error":{"message":"Host inference unavailable",'
                        '"type":"server_error"}}\n\n'
                    )
                finally:
                    release()

            return response_class(
                stream(),
                release=release,
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no"},
            )
        try:
            content, calls, usage, finish = [], {}, {}, "stop"
            async with aclosing(events()) as upstream:
                async for chunk in upstream:
                    if chunk.content:
                        content.append(chunk.content)
                    for fragment in chunk.tool_calls or []:
                        call = calls.setdefault(
                            fragment.get("index", 0),
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if fragment.get("id"):
                            call["id"] = fragment["id"]
                        for key in ("name", "arguments"):
                            call["function"][key] += fragment.get("function", {}).get(
                                key, ""
                            )
                    usage = chunk.usage or usage
                    finish = chunk.finish_reason or finish
            message = {"role": "assistant", "content": "".join(content)}
            if calls:
                message["tool_calls"] = [calls[index] for index in sorted(calls)]
            return {
                "id": ident,
                "created": created,
                "model": model,
                "object": "chat.completion",
                "usage": usage,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            }
        except Exception as exc:
            raise HTTPException(503, "Host inference unavailable.") from exc
        finally:
            release()
