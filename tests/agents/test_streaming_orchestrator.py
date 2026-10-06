import asyncio
import json
import threading
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.agents.streaming import stream_orchestrator
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import StreamChunk
from openjarvis.server.models import ChatCompletionRequest


@pytest.fixture
def anyio_backend():
    return "asyncio"


def agent_with_tool(engine):
    tool = MagicMock()
    tool.spec.name = "safe_tool"
    tool.spec.required_capabilities = []
    tool.to_openai_function.return_value = {
        "type": "function",
        "function": {"name": "safe_tool"},
    }
    agent = OrchestratorAgent(engine, "original", tools=[tool])
    # Keep the original executor's security wiring; mock only the final dispatch.
    agent._executor.execute = MagicMock(
        return_value=ToolResult(tool_name="safe_tool", content="42", success=True)
    )
    return agent


def request():
    return ChatCompletionRequest(
        model="worker",
        messages=[{"role": "user", "content": "Calculate"}],
        num_ctx=8192,
    )


@pytest.mark.anyio
async def test_text_streams_before_final_and_tool_calls_use_original_governance():
    engine = MagicMock()
    calls = []

    async def stream(messages, **kw):
        calls.append(kw)
        if len(calls) == 1:
            yield StreamChunk(
                tool_calls=[
                    {"index": 0, "function": {"name": "safe_", "arguments": '{"x":'}}
                ]
            )
            yield StreamChunk(
                tool_calls=[
                    {"index": 0, "function": {"name": "tool", "arguments": "1}"}}
                ]
            )
        else:
            yield StreamChunk(content="The result ")
            yield StreamChunk(content="is 42.")
        yield StreamChunk(
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        )

    engine.stream_full = stream
    agent = agent_with_tool(engine)
    agent._before_tool_call = MagicMock(return_value=True)
    events = [event async for event in stream_orchestrator(agent, request())]
    assert [e["text"] for e in events if "text" in e] == ["The result ", "is 42."]
    assert events[-1]["final_content"] == "The result is 42."
    agent._before_tool_call.assert_called_once_with("safe_tool", {"x": 1})
    assert json.loads(agent._executor.execute.call_args.args[0].arguments) == {"x": 1}
    assert agent._model == "original" and calls[0]["model"] == "worker"
    assert calls[0]["num_ctx"] == 8192
    assert calls[0]["require_tools"] is True
    assert [e["usage"] for e in events if "usage" in e][-1]["total_tokens"] == 10


@pytest.mark.anyio
async def test_cancellation_drains_current_tool_and_does_not_start_next():
    engine = MagicMock()

    async def stream(*args, **kw):
        yield StreamChunk(
            tool_calls=[
                {"index": i, "function": {"name": "safe_tool", "arguments": "{}"}}
                for i in range(2)
            ]
        )

    engine.stream_full = stream
    agent = agent_with_tool(engine)
    entered, release = threading.Event(), threading.Event()

    def execute(call):
        entered.set()
        release.wait(2)
        return ToolResult(tool_name=call.name, content="done", success=True)

    agent._executor.execute.side_effect = execute

    async def consume():
        async for _ in stream_orchestrator(agent, request()):
            pass

    task = asyncio.create_task(consume())
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent._executor.execute.call_count == 1


@pytest.mark.anyio
async def test_travel_search_runs_before_model_and_results_are_grounded():
    engine = MagicMock()
    agent = agent_with_tool(engine)
    events = []
    agent._before_tool_call = MagicMock(return_value=True)
    agent._executor.execute.return_value = ToolResult(
        tool_name="web_search",
        success=True,
        content="Source: https://www.wuhan.gov.cn/ — verified result",
        latency_seconds=1.2,
        metadata={
            "engine": "youcom",
            "sources": [{"url": "https://www.wuhan.gov.cn/"}],
            "taint": "internal",
        },
    )

    async def stream(messages, **kwargs):
        assert agent._executor.execute.call_count == 1
        assert any("https://www.wuhan.gov.cn/" in message.text for message in messages)
        assert "Do not invent sources" in messages[0].text
        yield StreamChunk(content="可以游览东湖。")

    engine.stream_full = stream
    req = request()
    req.messages[0].content = "我打算去武汉，武汉有什么好玩的"
    events = [event async for event in stream_orchestrator(agent, req)]
    assert events[0]["tool"] == "web_search"
    assert events[1]["success"] is True
    assert events[1]["latency"] == 1200
    assert events[1]["metadata"] == {
        "engine": "youcom",
        "sources": [{"url": "https://www.wuhan.gov.cn/"}],
    }
    call = agent._executor.execute.call_args.args[0]
    assert json.loads(call.arguments)["query"].startswith(req.messages[0].content)
    agent._before_tool_call.assert_called_once()


@pytest.mark.anyio
async def test_required_search_still_obeys_tool_authorization():
    engine = MagicMock()
    agent = agent_with_tool(engine)
    agent._before_tool_call = MagicMock(return_value=False)

    async def stream(messages, **kwargs):
        yield StreamChunk(content="搜索未获授权。")

    engine.stream_full = stream
    req = request()
    req.messages[0].content = "搜索网上最新旅游信息"
    events = [event async for event in stream_orchestrator(agent, req)]
    assert events[1]["success"] is False
    agent._executor.execute.assert_not_called()


@pytest.mark.anyio
async def test_historical_web_result_cannot_bypass_session_taint_on_followup():
    from openjarvis.speech.conversation import build_conversation_history
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    executed = []

    class Search(BaseTool):
        tool_id = "web_search"
        is_local = False

        @property
        def spec(self):
            return ToolSpec(name="web_search", description="Search", parameters={})

        def execute(self, **params):
            executed.append(params)
            return ToolResult(tool_name="web_search", content="result", success=True)

    engine = MagicMock()

    async def stream(messages, **kwargs):
        assert any("token=secret-value-123" in m.text for m in messages)
        yield StreamChunk(content="检索受到数据保护限制。")

    engine.stream_full = stream
    agent = OrchestratorAgent(engine, "test", tools=[Search()])
    history = build_conversation_history(
        [
            {
                "id": "a",
                "role": "assistant",
                "content": "Previous answer",
                "toolCalls": [
                    {
                        "tool": "web_search",
                        "status": "success",
                        "arguments": "{}",
                        "result": "token=secret-value-123",
                    }
                ],
            },
            {"role": "user", "content": "它的门票多少钱"},
        ]
    )
    req = ChatCompletionRequest(model="test", messages=history)
    events = [event async for event in stream_orchestrator(agent, req)]
    completion = next(e for e in events if e.get("stage") == "tool_complete")
    assert not completion["success"] and "Taint violation" in completion["result"]
    assert executed == []
