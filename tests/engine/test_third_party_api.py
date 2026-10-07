import json

import httpx
import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine.third_party_api import (
    ThirdPartyAPIEngine,
    validate_third_party_endpoint,
)


@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/chat/completions"])
def test_platform_urls_normalize(suffix):
    assert validate_third_party_endpoint("https://api.llm.ustc.edu.cn" + suffix) == (
        "https://api.llm.ustc.edu.cn"
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://api.test",
        "https://user:password@api.test/v1",
        "https://api.test:bad",
        "https://api.llm.ustc.edu.cn/?key=secret",
    ],
)
def test_invalid_endpoint_is_rejected(url):
    with pytest.raises(ValueError):
        validate_third_party_endpoint(url)


def test_arbitrary_provider_with_gateway_path_is_supported():
    assert validate_third_party_endpoint("https://provider.test/gateway/v1") == (
        "https://provider.test/gateway"
    )


@pytest.mark.parametrize(
    "model", ["qwen-chat", "ds-platform-id", "glm-platform-id", "vendor/model"]
)
@pytest.mark.asyncio
async def test_sync_and_stream_keep_model_auth_tools_and_empty_usage(model):
    payloads = []

    def handler(request):
        assert request.url == "https://api.llm.ustc.edu.cn/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer sample-key"
        payload = json.loads(request.content)
        payloads.append(payload)
        assert payload["model"] == model
        assert not {"num_ctx", "num_gpu", "think", "keep_alive"} & payload.keys()
        assert payload["tools"][0]["function"]["name"] == "get_time"
        if not payload["stream"]:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "你好",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "get_time",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
            {"choices": [{"delta": {"content": "你好"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1"}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"completion_tokens": 2}},
        ]
        return httpx.Response(
            200,
            text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n",
        )

    engine = ThirdPartyAPIEngine(
        host="https://api.llm.ustc.edu.cn", models=[model], api_key="sample-key"
    )
    engine._client.close()
    engine._client = httpx.Client(
        base_url=engine._host,
        headers=engine._headers,
        transport=httpx.MockTransport(handler),
    )
    engine._async_transport = httpx.MockTransport(handler)
    options = dict(
        model=f"third-party/{model}",
        num_ctx=2048,
        num_gpu=0,
        think=False,
        tools=[{"type": "function", "function": {"name": "get_time"}}],
    )
    messages = [Message(role=Role.USER, content="hello")]
    try:
        result = engine.generate(messages, **options)
        assert result["tool_calls"][0]["name"] == "get_time"
        assert (
            "".join([token async for token in engine.stream(messages, **options)])
            == "你好"
        )
        chunks = [chunk async for chunk in engine.stream_full(messages, **options)]
        assert chunks[-1].usage == {"completion_tokens": 2}
        assert any(chunk.tool_calls for chunk in chunks)
        assert engine.list_models() == [f"third-party/{model}"]
        assert len(payloads) == 3
    finally:
        engine.close()
