"""Loopback-only control for the native background voice assistant."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from openjarvis.speech.assistant import (
    DEFAULT_INTERRUPT_WORDS,
    NativeVoiceRuntime,
    VoiceOptions,
)

router = APIRouter(prefix="/v1/voice", tags=["voice"])


class StartVoiceRequest(BaseModel):
    language: Literal["zh", "en"] = "zh"
    voice_id: str = "zm_yunjian"
    speed: float = Field(default=1.1, ge=0.8, le=1.8)
    silence_ms: int = Field(default=1800, ge=700, le=2500)
    speak: bool = True
    fast_model: str = "qwen3.5:9b"
    strong_model: str = "deepseek-r1:14b"
    automatic_routing: bool = True
    voice_profile: str = ""
    character_id: Literal["jarvis-local", "mcu-jarvis"] = "jarvis-local"
    output_language: Literal["", "zh", "en"] = ""
    speech_detail: Literal["brief", "full"] = "brief"
    followup_seconds: float = Field(default=30, ge=10, le=300)
    interrupt_words: tuple[str, ...] = Field(
        default=DEFAULT_INTERRUPT_WORDS, max_length=16
    )

    @field_validator("interrupt_words")
    @classmethod
    def valid_interrupt_words(cls, words):
        if any(not word.strip() or len(word.strip()) > 40 for word in words):
            raise ValueError("Interrupt phrases must contain 1–40 characters")
        return tuple(dict.fromkeys(word.strip() for word in words))


def _require_local(request: Request) -> None:
    if request.client is None or request.client.host not in {
        "127.0.0.1",
        "::1",
        "testclient",
    }:
        raise HTTPException(
            403, "Microphone control is available only on this computer"
        )
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise HTTPException(403, "A remote website cannot control the microphone")


async def _respond(app, history, options):
    from openjarvis.server.models import ChatCompletionRequest
    from openjarvis.server.routes import (
        ModelRouteRequest,
        _obvious_mode,
        chat_completions,
        route_model,
    )

    prompt = history[-1]["content"]
    route = {"mode": _obvious_mode(prompt) or "chat", "model": options.fast_model}
    if getattr(app.state, "engine_name", "") == "api":
        route = {"mode": _obvious_mode(prompt) or "chat", "model": app.state.model}
    elif options.automatic_routing:
        route = await route_model(
            ModelRouteRequest(
                prompt=prompt[:6000],
                fast_model=options.fast_model,
                strong_model=options.strong_model,
            )
        )
    if options.speech_detail == "full" and any(
        m["role"] == "tool" and m.get("name") == "web_search" for m in history
    ):
        # A detailed follow-up may need to read a source rather than invent
        # details from a short snippet. Keep tools available, without forcing
        # a new search for an explanation that existing evidence supports.
        route["mode"] = "tool"
    yield {"model": route["model"]}
    yield {"mode": route["mode"]}
    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    response = await chat_completions(
        ChatCompletionRequest(
            model=route["model"],
            messages=history,
            temperature=0.3,
            max_tokens=2048,
            stream=True,
            stream_mode="agent" if route["mode"] == "tool" else "direct",
            character_id=options.character_id,
            output_language=options.response_language,
            speech_detail=options.speech_detail,
            num_ctx=(
                4096
                if route["mode"] == "chat"
                and not any(m["role"] == "tool" for m in history)
                else 8192
            ),
        ),
        request,
    )
    async for chunk in response.body_iterator:
        value = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in value.splitlines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            if event.get("work", {}).get("stage") in {"tool", "tool_complete"}:
                yield {"tool_event": event["work"]}
            if "final_content" in event:
                yield {"final_text": event["final_content"]}
            for choice in event.get("choices", []):
                if choice.get("finish_reason") == "error":
                    raise RuntimeError(
                        choice.get("delta", {}).get("content")
                        or "Model inference failed"
                    )
                content = choice.get("delta", {}).get("content")
                if content:
                    yield {"text": content}
            if event.get("usage"):
                yield {"usage": event["usage"]}


async def _delegate_background(app, history, options, conversation_id):
    """Queue an explicit voice delegation through the governed work service."""
    from openjarvis.server.models import ChatCompletionRequest
    from openjarvis.server.work_routes import service

    if getattr(app.state, "agent", None) is None:
        raise RuntimeError("Background work is not configured")
    model = (
        app.state.model
        if getattr(app.state, "engine_name", "") == "api"
        else options.strong_model
    )
    completion = ChatCompletionRequest(
        model=model,
        messages=history,
        temperature=0.3,
        max_tokens=4096,
        stream=True,
        stream_mode="agent",
        num_ctx=8192,
        character_id=options.character_id,
        output_language=options.response_language,
        speech_detail="full",
    )
    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    return await service(request).submit(
        completion.model_dump(mode="json"),
        conversation_id,
        "voice-" + uuid.uuid4().hex,
    )


def _control_lock(request: Request) -> asyncio.Lock:
    lock = getattr(request.app.state, "voice_control_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        request.app.state.voice_control_lock = lock
    return lock


async def _start_voice(body: StartVoiceRequest, request: Request):
    app = request.app
    from openjarvis.server.api_routes import _resolve_tts_backend

    if body.voice_profile:
        from openjarvis.speech.profiles import (
            profile_backend,
            resolve_profile,
            synthesize_profile,
        )

        try:
            selected = resolve_profile(
                body.voice_profile,
                body.output_language or body.language,
                body.character_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        tts = await profile_backend(app, selected) if body.speak else None
        if not hasattr(app.state, "voice_synthesizers"):
            app.state.voice_synthesizers = {}
        if tts is not None:
            app.state.voice_synthesizers[body.voice_profile] = (
                tts,
                selected,
            )

        def synthesize(text, *, voice_profile, **kwargs):
            if voice_profile != selected["id"]:
                raise ValueError("Voice selection changed")
            return synthesize_profile(tts, selected, text, **kwargs)
    else:
        tts = await _resolve_tts_backend(request) if body.speak else None
        synthesize = tts.synthesize if tts else lambda *args, **kwargs: None
    if body.speak and tts is None:
        raise HTTPException(501, "Voice output is not available")
    stream_callback = None
    if (
        tts is not None
        and hasattr(tts, "supports_streaming")
        and await asyncio.to_thread(tts.supports_streaming)
    ):
        if body.voice_profile:

            def stream_callback(text, *, voice_profile, **kwargs):
                from openjarvis.speech.profiles import stream_profile

                if voice_profile != selected["id"]:
                    raise ValueError("Voice selection changed")
                yield from stream_profile(tts, selected, text, **kwargs)
        else:
            stream_callback = tts.synthesize_stream
    runtime = getattr(app.state, "voice_runtime", None)
    was_standby = runtime is not None and runtime.running and not runtime.foreground
    if runtime is None:
        backend = getattr(app.state, "speech_backend", None)
        if backend is None:
            raise HTTPException(501, "Speech recognition is not configured")
        runtime = NativeVoiceRuntime(
            transcribe=backend.transcribe,
            respond=lambda history, options: _respond(app, history, options),
            synthesize=synthesize,
            synthesize_stream=stream_callback,
        )
        app.state.voice_runtime = runtime
        runtime.delegate = lambda history, options: _delegate_background(
            app, history, options, runtime.session_id
        )
    elif tts is not None:
        runtime.synthesize = synthesize
        runtime.synthesize_stream = stream_callback
    if runtime is not None and getattr(runtime, "delegate", None) is None:
        runtime.delegate = lambda history, options: _delegate_background(
            app, history, options, runtime.session_id
        )
    try:
        await runtime.start(VoiceOptions(**body.model_dump()))
        if was_standby:
            await runtime.standby()
    except Exception as exc:
        raise HTTPException(503, f"Microphone could not start: {exc}") from exc
    return runtime.snapshot()


@router.post("/start")
async def start_voice(body: StartVoiceRequest, request: Request):
    _require_local(request)
    from openjarvis.server.voice_lifecycle import cancel_restore, ensure_restore
    from openjarvis.speech.preferences import save_preference

    await cancel_restore(request.app)
    async with _control_lock(request):
        if getattr(request.app.state, "_managed_runtime_stopping", False):
            raise HTTPException(503, "Voice service is shutting down")
        result = await _start_voice(body, request)
        try:
            save_preference(enabled=True, options=body.model_dump(mode="json"))
        except (OSError, ValueError) as exc:
            await request.app.state.voice_runtime.stop()
            request.app.state.voice_desired_enabled = False
            raise HTTPException(
                507, "Microphone stopped because voice settings could not be saved"
            ) from exc
        request.app.state.voice_desired_enabled = True
        request.app.state.voice_restore_error = ""
        ensure_restore(request.app)
        return result


@router.post("/stop")
async def stop_voice(request: Request):
    _require_local(request)
    from openjarvis.server.voice_lifecycle import cancel_restore
    from openjarvis.speech.preferences import save_preference

    request.app.state.voice_desired_enabled = False
    # Cancel a pending restore before waiting for its control lock. A slow
    # voice-model load cannot resurrect the microphone after explicit off.
    await cancel_restore(request.app)
    async with _control_lock(request):
        persistence_error = None
        try:
            save_preference(enabled=False)
        except (OSError, ValueError) as exc:
            persistence_error = exc
        runtime = getattr(request.app.state, "voice_runtime", None)
        if runtime:
            await runtime.stop()
        if persistence_error is not None:
            raise HTTPException(
                507,
                "Microphone stopped, but off preference could not be saved; "
                "check file permissions before restarting",
            ) from persistence_error
    return {"running": False, "phase": "stopped"}


@router.post("/standby")
async def standby_voice(request: Request):
    _require_local(request)
    async with _control_lock(request):
        runtime = getattr(request.app.state, "voice_runtime", None)
        if runtime:
            await runtime.standby()
            return runtime.snapshot()
    return {"running": False, "phase": "stopped"}


@router.get("/state")
async def voice_state(request: Request):
    _require_local(request)
    runtime = getattr(request.app.state, "voice_runtime", None)
    result = (
        runtime.snapshot()
        if runtime
        else {"running": False, "phase": "stopped", "revision": 0, "messages": []}
    )
    task = getattr(request.app.state, "voice_restore_task", None)
    result["restoring"] = task is not None and not task.done() and not result["running"]
    result["desired_enabled"] = getattr(
        request.app.state, "voice_desired_enabled", None
    )
    if not result.get("error"):
        result["error"] = getattr(request.app.state, "voice_restore_error", "")
    return result
