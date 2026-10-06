"""The real chat/agent path remains governed when used by background work."""

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import StreamChunk
from openjarvis.server.app import create_app
from openjarvis.server.work_routes import secured_events, service

BODY = {
    "conversation_id": "conversation",
    "request_key": "one-task",
    "completion": {
        "model": "worker",
        "messages": [{"role": "user", "content": "Calculate"}],
        "max_tokens": 2048,
        "stream_mode": "agent",
    },
}


def make_app(engine):
    tool = MagicMock()
    tool.spec.name = "safe_tool"
    tool.spec.required_capabilities = []
    tool.to_openai_function.return_value = {
        "type": "function",
        "function": {"name": "safe_tool"},
    }
    agent = OrchestratorAgent(engine, "original", tools=[tool])
    agent._executor.execute = MagicMock(
        return_value=ToolResult(tool_name="safe_tool", content="42", success=True)
    )
    cfg = JarvisConfig()
    cfg.security.enabled = cfg.analytics.enabled = cfg.traces.enabled = False
    cfg.agent.context_from_memory = False
    app = create_app(engine, "test", agent=agent, config=cfg, api_key="test-key")
    return app, agent


async def poll(client, job_id, status):
    async with asyncio.timeout(4):
        while True:
            result = (await client.get(f"/v1/work/jobs/{job_id}")).json()
            if result["status"] == status:
                return result
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("allow", [True, False])
async def test_background_uses_real_governance_and_does_not_block_foreground(
    tmp_path, monkeypatch, allow
):
    monkeypatch.setenv("OPENJARVIS_WORK_DB", str(tmp_path / "work.db"))
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.list_models.return_value = ["worker", "chat"]
    entered, release = threading.Event(), threading.Event()
    rounds = []

    async def stream_full(messages, **kwargs):
        rounds.append(kwargs)
        if len(rounds) == 1:
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "function": {"name": "safe_tool", "arguments": '{"x":1}'},
                    }
                ]
            )
        else:
            yield StreamChunk(
                content="The result is 42." if allow else "Tool was denied."
            )
        yield StreamChunk(finish_reason="stop", usage={"total_tokens": 7})

    async def stream(*args, **kwargs):
        yield "Fast foreground answer"

    engine.stream_full, engine.stream = stream_full, stream
    app, agent = make_app(engine)
    agent._before_tool_call = MagicMock(return_value=allow)

    def dispatch(call):
        entered.set()
        release.wait(3)
        return ToolResult(tool_name=call.name, content="42", success=True)

    agent._executor.execute.side_effect = dispatch
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        try:
            submitted = await client.post("/v1/work/jobs", json=BODY)
            assert submitted.status_code == 202
            job_id = submitted.json()["id"]
            assert (await client.post("/v1/work/jobs", json=BODY)).json()[
                "id"
            ] == job_id
            if allow:
                assert await asyncio.to_thread(entered.wait, 1)
                async with asyncio.timeout(1):
                    foreground = await client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "chat",
                            "messages": [{"role": "user", "content": "Hi"}],
                            "stream": True,
                            "stream_mode": "direct",
                        },
                    )
                assert "Fast foreground answer" in foreground.text
                release.set()
            result = await poll(client, job_id, "completed")
            assert result["tool_calls"][0]["status"] == (
                "success" if allow else "error"
            )
            assert result["usage"]["total_tokens"] == 14
            agent._before_tool_call.assert_called_once_with("safe_tool", {"x": 1})
            assert agent._executor.execute.call_count == int(allow)
            assert agent._model == "original" and rounds[0]["model"] == "worker"
        finally:
            release.set()
            current = getattr(app.state, "background_work", None)
            if current:
                assert await current.close()
                current.store.close()


@pytest.mark.asyncio
async def test_work_rejects_remote_origin_auth_bypass_and_raw_client_tools(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENJARVIS_WORK_DB", str(tmp_path / "work.db"))
    app, _ = make_app(MagicMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        assert (await client.get("/v1/work/jobs")).status_code == 401
        client.headers["Authorization"] = "Bearer test-key"
        assert (
            await client.get(
                "/v1/work/jobs", headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
        raw = {
            **BODY,
            "completion": {
                **BODY["completion"],
                "tools": [{"function": {"name": "unsafe"}}],
            },
        }
        assert (await client.post("/v1/work/jobs", json=raw)).status_code == 422
        raw = {**BODY, "completion": {**BODY["completion"], "stream_mode": "direct"}}
        assert (await client.post("/v1/work/jobs", json=raw)).status_code == 422
        assert not hasattr(app.state, "background_work")


@pytest.mark.asyncio
async def test_sse_parser_handles_fragmented_utf8_and_ignores_duplicate_named_tools(
    monkeypatch,
):
    from openjarvis.server import routes

    tool = {"stage": "tool_complete", "tool": "web_search", "success": True}

    async def completion(req, request):
        async def stream():
            payload = (
                "data: "
                + json.dumps({"work": tool})
                + "\n\n"
                + "event: tool_call_end\ndata: "
                + json.dumps(tool)
                + "\n\n"
                + 'data: {"choices":[{"delta":{"content":"中文"},'
                '"finish_reason":null}]}\n\n'
                + 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                '"final_content":"最终结果"}\n\n'
            ).encode()
            for byte in payload:
                yield bytes([byte])

        return StreamingResponse(stream())

    monkeypatch.setattr(routes, "chat_completions", completion)
    events = [event async for event in secured_events(MagicMock(), BODY["completion"])]
    assert sum(event.get("stage") == "tool_complete" for event in events) == 1
    assert events[-1]["final_content"] == "最终结果"
    assert "".join(event.get("text", "") for event in events) == "中文"


@pytest.mark.asyncio
async def test_sse_disconnect_is_not_completion(monkeypatch):
    from openjarvis.server import routes

    async def completion(req, request):
        async def stream():
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'

        return StreamingResponse(stream())

    monkeypatch.setattr(routes, "chat_completions", completion)
    with pytest.raises(RuntimeError, match="disconnected"):
        _ = [event async for event in secured_events(MagicMock(), BODY["completion"])]


@pytest.mark.asyncio
async def test_work_service_wires_terminal_events_to_local_voice_only(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENJARVIS_WORK_DB", str(tmp_path / "work.db"))
    app, _ = make_app(MagicMock())
    voice = MagicMock()
    voice.notify_background = AsyncMock()
    app.state.voice_runtime = voice
    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    current = service(request)
    await current.on_terminal({"id": "job", "status": "completed"})
    voice.notify_background.assert_awaited_once_with(
        {"id": "job", "status": "completed"}
    )
    assert await current.close()
    current.store.close()


@pytest.mark.asyncio
async def test_resume_route_uses_distinct_checkpoint_action(monkeypatch):
    from openjarvis.server import work_routes

    app, _ = make_app(MagicMock())
    current = MagicMock()
    current.start = AsyncMock()
    current.resume = AsyncMock(
        return_value={"id": "resumed", "status": "queued", "phase": "queued"}
    )
    monkeypatch.setattr(work_routes, "service", lambda request: current)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        response = await client.post("/v1/work/jobs/original/resume")
    assert response.status_code == 202
    assert response.json()["id"] == "resumed"
    current.resume.assert_awaited_once_with("original")


@pytest.mark.asyncio
async def test_metrics_route_returns_aggregate_without_job_content(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENJARVIS_WORK_DB", str(tmp_path / "work.db"))
    app, _ = make_app(MagicMock())
    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    current = service(request)
    current.store.submit(
        {"model": "worker", "messages": [{"role": "user", "content": "private"}]},
        "chat",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        response = await client.get("/v1/work/jobs/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["total_jobs"] == 1
    assert "private" not in response.text
    assert await current.close()
    current.store.close()
