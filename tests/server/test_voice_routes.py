"""Native voice reuses streaming inference and rejects remote mic control."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig
from openjarvis.server.app import create_app
from openjarvis.server.voice_routes import _respond
from openjarvis.speech.assistant import VoiceOptions


@pytest.fixture
def anyio_backend():
    return "asyncio"


def app_with_stream():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.list_models.return_value = ["test-model"]

    async def stream(*args, **kwargs):
        yield "你好"
        yield "，我在。"

    engine.stream = stream
    cfg = JarvisConfig()
    cfg.security.enabled = False
    cfg.analytics.enabled = False
    cfg.traces.enabled = False
    cfg.agent.context_from_memory = False
    return create_app(engine, "test-model", config=cfg)


@pytest.mark.anyio
async def test_native_voice_uses_actual_chat_stream():
    app = app_with_stream()
    options = VoiceOptions(fast_model="test-model", automatic_routing=False)
    events = [
        event
        async for event in _respond(app, [{"role": "user", "content": "你好"}], options)
    ]
    assert events[0] == {"model": "test-model"}
    assert "".join(event.get("text", "") for event in events) == "你好，我在。"
    assert any(event.get("usage") for event in events)


@pytest.mark.anyio
async def test_native_voice_routes_with_its_current_backend_instance(monkeypatch):
    from fastapi.responses import StreamingResponse

    from openjarvis.server import routes

    app = app_with_stream()
    seen = {}

    async def route(body, request):
        seen["app"] = request.app
        return {"mode": "chat", "model": body.fast_model}

    async def chat(req, request):
        async def stream():
            yield 'data: {"choices":[{"delta":{"content":"收到"}}]}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream())

    monkeypatch.setattr(routes, "route_model", route)
    monkeypatch.setattr(routes, "chat_completions", chat)
    options = VoiceOptions(fast_model="test-model", automatic_routing=True)
    events = [
        event
        async for event in _respond(
            app, [{"role": "user", "content": "你好呀"}], options
        )
    ]
    assert seen["app"] is app
    assert events[0] == {"model": "test-model"}
    assert any(event.get("text") == "收到" for event in events)


@pytest.mark.anyio
@pytest.mark.parametrize("followup", [False, True])
async def test_native_voice_forwards_mode_tool_records_and_authoritative_final(
    monkeypatch,
    followup,
):
    from fastapi.responses import StreamingResponse

    from openjarvis.server import routes

    tool = {
        "stage": "tool_complete",
        "tool": "web_search",
        "success": True,
        "latency": 100,
        "metadata": {"sources": [{"url": "https://example.com"}]},
    }

    async def chat(req, request):
        assert req.stream_mode == "agent"
        if followup:
            assert req.num_ctx == 8192 and req.speech_detail == "full"

        async def stream():
            yield "data: " + json.dumps({"work": tool}) + "\n\n"
            # Named tool events must not be duplicated in native records.
            yield "event: tool_call_end\ndata: " + json.dumps(tool) + "\n\n"
            yield (
                'data: {"final_content":"真实结果","choices":'
                '[{"delta":{},"finish_reason":"stop"}]}\n\n'
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream())

    monkeypatch.setattr(routes, "chat_completions", chat)
    options = VoiceOptions(
        fast_model="test-model",
        automatic_routing=False,
        speech_detail="full" if followup else "brief",
    )
    history = [{"role": "user", "content": "武汉旅游攻略"}]
    if followup:
        history = [
            {
                "role": "tool",
                "name": "web_search",
                "tool_call_id": "prior",
                "content": "Historical source",
            },
            {"role": "user", "content": "具体说说"},
        ]
    events = [event async for event in _respond(app_with_stream(), history, options)]
    assert events[1] == {"mode": "tool"}
    assert [e["tool_event"] for e in events if "tool_event" in e] == [tool]
    assert events[-1] == {"final_text": "真实结果"}


def test_remote_clients_cannot_activate_microphone():
    app = app_with_stream()
    client = TestClient(app, client=("192.0.2.8", 1234))
    assert client.post("/v1/voice/start", json={}).status_code == 403
    assert client.post("/v1/voice/stop").status_code == 403
    assert client.get("/v1/voice/state").status_code == 403
    assert not hasattr(app.state, "voice_runtime")


def test_remote_website_cannot_control_local_microphone():
    with TestClient(app_with_stream()) as client:
        assert (
            client.post(
                "/v1/voice/start",
                json={},
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )


def test_transcription_api_simplifies_chinese_but_not_english():
    from openjarvis.speech._stubs import TranscriptionResult

    app = app_with_stream()
    app.state.speech_backend = MagicMock()
    app.state.speech_backend.transcribe.return_value = TranscriptionResult(
        text="賈維斯，請開啟瀏覽器。", language="zh"
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/speech/transcribe",
            files={"file": ("voice.wav", b"audio", "audio/wav")},
        )
        assert response.json()["text"] == "贾维斯，请开启浏览器。"
        assert app.state.speech_backend.transcribe.call_args.kwargs["language"] == "zh"
        app.state.speech_backend.transcribe.return_value.text = "Hello Jarvis."
        response = client.post(
            "/v1/speech/transcribe",
            data={"language": "en"},
            files={"file": ("voice.wav", b"audio", "audio/wav")},
        )
        assert response.json()["text"] == "Hello Jarvis."
        assert app.state.speech_backend.transcribe.call_args.kwargs["language"] == "en"


def test_default_state_is_stopped():
    with TestClient(app_with_stream()) as client:
        assert client.get("/v1/voice/state").json()["running"] is False
        assert (
            client.post("/v1/voice/start", json={"language": "fr"}).status_code == 422
        )


def test_voice_control_settings_are_bounded_and_preserve_disabled_interrupts():
    from openjarvis.server.voice_routes import StartVoiceRequest

    assert StartVoiceRequest().silence_ms == 1800
    assert StartVoiceRequest(interrupt_words=[]).interrupt_words == ()
    assert StartVoiceRequest(interrupt_words=[" pause ", "pause"]).interrupt_words == (
        "pause",
    )
    with TestClient(app_with_stream()) as client:
        for invalid in [
            {"followup_seconds": 0},
            {"followup_seconds": 301},
            {"interrupt_words": [""]},
            {"interrupt_words": ["x" * 41]},
        ]:
            assert client.post("/v1/voice/start", json=invalid).status_code == 422
