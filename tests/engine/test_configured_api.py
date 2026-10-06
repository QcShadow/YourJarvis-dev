import json

import httpx
import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine._discovery import _make_engine
from openjarvis.engine.configured_api import ConfiguredAPIEngine, ensure_registered
from openjarvis.engine.ollama import OllamaEngine


@pytest.mark.asyncio
async def test_gateway_stream_error_is_not_an_empty_success():
    engine = ConfiguredAPIEngine("http://host.test/v1", default_model="host-model")
    engine._async_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content='data: {"error":{"message":"unavailable"}}\n\n',
            headers={"content-type": "text/event-stream"},
        )
    )
    try:
        with pytest.raises(EngineConnectionError, match="inference stream failed"):
            async for _ in engine.stream_full(
                [Message(role=Role.USER, content="hello")], model="host-model"
            ):
                pass
    finally:
        engine.close()


def test_custom_api_keeps_prefix_model_and_auth():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})

    engine = ConfiguredAPIEngine(
        "https://provider.test/compatible-mode/v1",
        api_key="sample-secret",
        default_model="my-model",
    )
    engine._client.close()
    engine._client = httpx.Client(
        base_url=engine._host,
        headers=engine._headers,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = engine.generate(
            [Message(role=Role.USER, content="hello")],
            model="my-model",
            num_ctx=2048,
            num_gpu=0,
            think=False,
        )
        assert result["content"] == "你好"
        assert seen[0].url.path == "/compatible-mode/v1/chat/completions"
        assert seen[0].headers["authorization"] == "Bearer sample-secret"
        assert json.loads(seen[0].content)["model"] == "my-model"
        assert "num_ctx" not in json.loads(seen[0].content)
        assert "num_gpu" not in json.loads(seen[0].content)
        assert "think" not in json.loads(seen[0].content)
        assert engine.list_models() == ["my-model"]
    finally:
        engine.close()


@pytest.mark.parametrize(
    "status,healthy",
    [(200, True), (404, True), (405, True), (401, False), (403, False), (429, False)],
)
def test_health_uses_no_paid_generation(status, healthy):
    engine = ConfiguredAPIEngine("https://api.test/v1", default_model="chat")
    engine._client.close()

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return httpx.Response(status)

    engine._client = httpx.Client(
        base_url=engine._host, transport=httpx.MockTransport(handler)
    )
    try:
        assert engine.health() is healthy
    finally:
        engine.close()


def test_api_factory_uses_selected_key(monkeypatch):
    ensure_registered()
    cfg = JarvisConfig()
    cfg.engine.api.host = "http://localhost:1234/v1"
    cfg.intelligence.default_model = "qwen-local"
    cfg.engine.api.api_key_env = "FRIEND_PROVIDER_KEY"
    monkeypatch.setenv("FRIEND_PROVIDER_KEY", "different-secret")
    engine = _make_engine("api", cfg)
    try:
        assert engine._headers == {"Authorization": "Bearer different-secret"}
        assert engine.list_models() == ["qwen-local"]
    finally:
        engine.close()


@pytest.mark.asyncio
async def test_lite_options_reach_sync_and_stream_paths():
    cfg = JarvisConfig()
    cfg.engine.ollama.num_gpu = 0
    cfg.engine.ollama.num_ctx = 2048
    EngineRegistry.register_value("ollama", OllamaEngine)
    engine = _make_engine("ollama", cfg)
    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        if payload["stream"]:
            return httpx.Response(
                200, text='{"message":{"content":"ok"},"done":true}\n'
            )
        return httpx.Response(200, json={"message": {"content": "ok"}})

    engine._client.close()
    engine._client = httpx.Client(
        base_url=engine._host, transport=httpx.MockTransport(handler)
    )
    engine._async_transport = httpx.MockTransport(handler)
    try:
        messages = [Message(role=Role.USER, content="hello")]
        engine.generate(messages, model="qwen2.5:0.5b")
        async for _ in engine.stream(messages, model="qwen2.5:0.5b"):
            pass
        async for _ in engine.stream_full(messages, model="qwen2.5:0.5b"):
            pass
        assert len(payloads) == 3
        assert all(p["options"]["num_ctx"] == 2048 for p in payloads)
        assert all(p["options"]["num_gpu"] == 0 for p in payloads)
    finally:
        engine.close()
