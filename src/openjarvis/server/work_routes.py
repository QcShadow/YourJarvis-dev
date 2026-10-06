"""Local background work, reusing the ordinary governed chat execution path."""

from __future__ import annotations

import asyncio
import codecs
import json
import os
from contextlib import aclosing
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.server.models import ChatCompletionRequest
from openjarvis.server.work_jobs import (
    BackgroundWork,
    JobConflict,
    QueueFull,
    WorkStore,
)

router = APIRouter(prefix="/v1/work/jobs", tags=["background-work"])


class SubmitWork(BaseModel):
    completion: ChatCompletionRequest
    conversation_id: str = Field(min_length=1, max_length=128)
    request_key: str = Field(min_length=1, max_length=128)


def require_local(request):
    if request.client is None or request.client.host not in {
        "127.0.0.1",
        "::1",
        "testclient",
    }:
        raise HTTPException(403, "Background work is available only on this computer")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise HTTPException(403, "A remote website cannot access local work")


async def secured_events(app, payload):
    """Parse the existing SSE response, not a second ungoverned agent loop."""
    from openjarvis.server.routes import chat_completions

    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    response = await chat_completions(
        ChatCompletionRequest.model_validate(payload), request
    )
    if not hasattr(response, "body_iterator"):
        raise RuntimeError("Background work did not return a streaming response")
    decoder, buffer, content = codecs.getincrementaldecoder("utf-8")(), "", ""
    finished = False
    async with aclosing(response.body_iterator) as chunks:
        async for part in chunks:
            buffer += decoder.decode(part) if isinstance(part, bytes) else part
            if len(buffer) > 1000000:
                raise RuntimeError("Background SSE frame exceeded its limit")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                # Named tool events repeat the same `work` record. Do not execute
                # or display a tool twice just because both forms are emitted.
                if any(line.startswith("event:") for line in frame.splitlines()):
                    continue
                data = "\n".join(
                    line[5:].lstrip()
                    for line in frame.splitlines()
                    if line.startswith("data:")
                )
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                if event.get("error"):
                    raise RuntimeError(str(event["error"]))
                if event.get("work"):
                    yield event["work"]
                if event.get("usage"):
                    yield {"usage": event["usage"]}
                for choice in event.get("choices", []):
                    text = choice.get("delta", {}).get("content")
                    if text:
                        content += text
                        yield {"text": text}
                    reason = choice.get("finish_reason")
                    if reason:
                        finished = True
                        yield {
                            "final_content": event.get("final_content", content),
                            "finish_reason": reason,
                        }
        if not finished:
            raise RuntimeError(
                "Background response disconnected without a final result"
            )


def service(request):
    require_local(request)
    state = request.app.state
    if getattr(state, "_managed_runtime_stopping", False):
        raise HTTPException(503, "Server is shutting down")
    current = getattr(state, "background_work", None)
    if current is None:
        # No await between lookup and assignment: one service per app event loop.
        path = (
            Path(os.environ["OPENJARVIS_WORK_DB"])
            if os.environ.get("OPENJARVIS_WORK_DB")
            else get_config_dir() / "work-jobs.sqlite3"
        )
        store = WorkStore(path)
        async def notify_terminal(job):
            runtime = getattr(request.app.state, "voice_runtime", None)
            notify = getattr(runtime, "notify_background", None)
            if callable(notify):
                await notify(job)

        current = BackgroundWork(
            store,
            lambda payload: secured_events(request.app, payload),
            on_terminal=notify_terminal,
        )
        state.background_work = current
    return current


@router.post("", status_code=202)
async def submit(body: SubmitWork, request: Request):
    require_local(request)
    req = body.completion
    if req.tools or req.stream_mode != "agent":
        raise HTTPException(422, "Work must use the server's governed agent and tools")
    if (
        not req.messages
        or req.messages[-1].role != "user"
        or not req.messages[-1].content.strip()
    ):
        raise HTTPException(422, "Work needs a nonempty final user request")
    if len(req.messages) > 200 or sum(len(m.content) for m in req.messages) > 120000:
        raise HTTPException(422, "Background conversation exceeds its input limit")
    if not 1 <= req.max_tokens <= 16384:
        raise HTTPException(
            422, "Work output budget must be between 1 and 16384 tokens"
        )
    if getattr(request.app.state, "agent", None) is None:
        raise HTTPException(503, "Configure a server agent before submitting work")
    req = req.model_copy(update={"stream": True})
    try:
        return await service(request).submit(
            req.model_dump(mode="json"), body.conversation_id, body.request_key
        )
    except QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
async def list_jobs(request: Request, conversation_id: str | None = None):
    current = service(request)
    await current.start()
    return {"jobs": await asyncio.to_thread(current.store.list, conversation_id)}


@router.get("/metrics")
async def metrics(request: Request):
    current = service(request)
    await current.start()
    return await asyncio.to_thread(current.store.metrics)


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request):
    current = service(request)
    await current.start()
    job = await asyncio.to_thread(current.store.get, job_id)
    if job is None:
        raise HTTPException(404, "Work not found")
    return job


async def control(job_id, request, *, action="cancel"):
    current = service(request)
    await current.start()
    try:
        if action == "retry":
            return await current.retry(job_id)
        if action == "resume":
            return await current.resume(job_id)
        return await current.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Work not found") from exc
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    return await control(job_id, request)


@router.post("/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, request: Request):
    return await control(job_id, request, action="retry")


@router.post("/{job_id}/resume", status_code=202)
async def resume_job(job_id: str, request: Request):
    return await control(job_id, request, action="resume")
