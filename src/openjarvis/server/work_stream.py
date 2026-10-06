"""SSE adapter for true orchestrator streaming, shared by chat and work."""

import json
import time
import uuid

from fastapi.responses import StreamingResponse

from openjarvis.agents.streaming import stream_orchestrator


def orchestrator_response(agent, model, req, *, trace_store, bus, memory_service):
    from openjarvis.server.routes import _record_completed_exchange

    async def generate():
        chunk_id = "chatcmpl-" + uuid.uuid4().hex[:12]
        start = time.time()
        usage = {}

        def chunk(delta=None, finish=None, **extra):
            return (
                "data: "
                + json.dumps(
                    {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": delta or {}, "finish_reason": finish}
                        ],
                        **extra,
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )

        yield chunk({"role": "assistant"})
        try:
            async for event in stream_orchestrator(agent, req):
                if "text" in event:
                    yield chunk({"content": event["text"]})
                if "usage" in event:
                    usage = event["usage"]
                if "stage" in event:
                    yield chunk(work=event)
                    if event["stage"] in {"tool", "tool_complete"}:
                        name = (
                            "tool_call_start"
                            if event["stage"] == "tool"
                            else "tool_call_end"
                        )
                        payload = json.dumps(event, ensure_ascii=False)
                        yield f"event: {name}\ndata: {payload}\n\n"
                if "final_content" in event:
                    content = event["final_content"]
                    query = req.messages[-1].content if req.messages else ""
                    _record_completed_exchange(
                        memory_service,
                        query,
                        content,
                        bus=bus,
                        source="server.chat.stream",
                    )
                    if trace_store is not None:
                        from openjarvis.traces.collector import record_response_trace

                        record_response_trace(
                            trace_store,
                            query=query,
                            result=content,
                            model=model,
                            engine=getattr(agent._engine, "engine_id", ""),
                            started_at=start,
                            ended_at=time.time(),
                        )
                    yield chunk(
                        finish=event["finish_reason"],
                        usage=usage,
                        final_content=content,
                    )
        except Exception as exc:
            yield chunk({"content": f"\n\nTask error: {exc}"}, finish="error")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
