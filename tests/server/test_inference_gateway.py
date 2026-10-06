import json

from fastapi.testclient import TestClient

from openjarvis.engine._stubs import StreamChunk
from openjarvis.server.friends import create_friends_app, invite_member


class Engine:
    def __init__(self):
        self.requests = []

    async def stream_full(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        if messages[-1].role.value == "tool":
            yield StreamChunk(content="计算结果是 42。")
            yield StreamChunk(finish_reason="stop")
        else:
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":',
                        },
                    }
                ]
            )
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "function": {"arguments": '"6*7"}'},
                    }
                ]
            )
            yield StreamChunk(finish_reason="tool_calls", usage={"total_tokens": 9})

    def close(self):
        pass


def test_complete_client_tool_loop_stays_on_recipient(tmp_path):
    path = tmp_path / "members.json"
    token = invite_member(path, "recipient")
    engine = Engine()
    app = create_friends_app(engine, model="host-private-model", members_path=path)
    with TestClient(app) as client:
        assert client.get("/v1/models").status_code == 401
        headers = {"Authorization": "Bearer " + token}
        assert (
            client.get("/v1/models", headers=headers).json()["data"][0]["id"]
            == "host-model"
        )
        body = {
            "model": "host-model",
            "messages": [
                {"role": "system", "content": "recipient's own persona"},
                {"role": "user", "content": "calculate 6*7"},
            ],
            "tools": [{"type": "function", "function": {"name": "calculator"}}],
        }
        result = client.post("/v1/chat/completions", headers=headers, json=body)
        assert result.status_code == 200, result.text
        message = result.json()["choices"][0]["message"]
        assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
            "expression": "6*7"
        }
        messages, options = engine.requests[0]
        assert messages[0].content == "recipient's own persona"
        assert options["model"] == "host-private-model"
        assert options["tools"] == body["tools"]
        assert "host" not in message["content"]
        body["messages"].extend(
            [message, {"role": "tool", "tool_call_id": "call_1", "content": "42"}]
        )
        result = client.post("/v1/chat/completions", headers=headers, json=body)
        assert result.json()["choices"][0]["message"]["content"] == "计算结果是 42。"
        assert engine.requests[-1][0][-1].tool_call_id == "call_1"
        assert client.get("/v1/memory", headers=headers).status_code == 404
        assert client.get("/v1/deployment/settings", headers=headers).status_code == 404


def test_stream_auth_revoke_and_admission_cleanup(tmp_path):
    path = tmp_path / "members.json"
    token = invite_member(path, "recipient")
    app = create_friends_app(Engine(), model="chosen", members_path=path)
    headers = {"Authorization": "Bearer " + token}
    body = {
        "model": "host-model",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    with TestClient(app) as client:
        for _ in range(2):
            result = client.post("/v1/chat/completions", headers=headers, json=body)
            assert result.status_code == 200
            assert '"tool_calls"' in result.text
            assert "data: [DONE]" in result.text
        body["model"] = "unshared-model"
        assert (
            client.post("/v1/chat/completions", headers=headers, json=body).status_code
            == 404
        )
        path.write_text("{}")
        assert (
            client.post("/v1/chat/completions", headers=headers, json=body).status_code
            == 401
        )
