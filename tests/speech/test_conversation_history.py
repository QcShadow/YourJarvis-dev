"""Follow-ups retain retrieval evidence without replaying actions."""

import json
from copy import deepcopy

from openjarvis.speech.conversation import (
    build_conversation_history,
    inherited_sources,
)


def turn(name="answer", result="Original retrieved detail", status="success"):
    return {
        "id": name,
        "role": "assistant",
        "content": "Model-written claim",
        "toolCalls": [
            {
                "id": "tool-1",
                "tool": "web_search",
                "status": status,
                "arguments": '{"query":"武汉旅游"}',
                "result": result,
                "metadata": {
                    "sources": [
                        {
                            "url": "https://example.com/source",
                            "title": "Source",
                            "retrieved_at": "2026-09-30T01:00:00Z",
                        }
                    ]
                },
            }
        ],
    }


def test_history_preserves_tool_pairs_original_dates_and_untrusted_boundary():
    messages = [
        {"role": "user", "content": "武汉旅游"},
        turn(),
        {"role": "user", "content": "具体说说"},
    ]
    original = deepcopy(messages)
    history = build_conversation_history(messages)
    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert history[1]["tool_calls"][0]["id"] == history[2]["tool_call_id"]
    assert "not a new search" in history[2]["content"]
    payload = json.loads(history[2]["content"].split("\n", 1)[1])
    assert payload["data"] == "Original retrieved detail"
    assert payload["sources"][0]["retrieved_at"] == "2026-09-30T01:00:00Z"
    assert history[3]["content"] == "Model-written claim"
    assert messages == original
    assert inherited_sources(messages)[0]["retrieved_at"] == "2026-09-30T01:00:00Z"


def test_only_latest_web_turn_is_replayed_and_result_size_is_bounded():
    messages = [turn("old", "Old detail"), turn("new", "A" * 7000)]
    history = build_conversation_history(messages)
    tools = [m for m in history if m["role"] == "tool"]
    assert len(tools) == 1
    assert "Old detail" not in str(history)
    payload = json.loads(tools[0]["content"].split("\n", 1)[1])
    assert len(payload["data"]) == 6000 and payload["truncated"]


def test_failed_search_and_unfinished_local_actions_are_not_replayed_as_success():
    failed = turn(status="error")
    unfinished = turn("unfinished", status="running")
    unfinished["toolCalls"].append(
        {"tool": "shell_exec", "status": "success", "result": "Private file"}
    )
    history = build_conversation_history([failed, unfinished])
    tools = [m for m in history if m["role"] == "tool"]
    assert len(tools) == 1 and '"status": "error"' in tools[0]["content"]
    assert inherited_sources([failed, unfinished]) == []
    assert "Private file" not in str(history)


def test_invalid_tool_arguments_and_private_sources_do_not_break_history():
    answer = turn()
    answer["toolCalls"][0]["arguments"] = "not-json"
    answer["toolCalls"][0]["metadata"]["sources"] += [
        None,
        {"url": "http://localhost", "title": "Private"},
    ]
    history = build_conversation_history([answer])
    assert history[0]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert "localhost" not in str(history)


def test_replayed_external_history_still_seeds_secret_taint():
    from openjarvis.security.taint import TaintLabel, auto_detect_taint

    history = build_conversation_history([turn(result="token=secret-value-123")])
    assert auto_detect_taint(history[1]["content"]).has(TaintLabel.SECRET)
