"""Bounded connection recovery with explicit fallback provenance."""

from unittest.mock import MagicMock

import httpx
import pytest

from openjarvis.tools.web_search import WebSearchTool


@pytest.fixture
def search(monkeypatch):
    monkeypatch.delenv("YOUDOTCOM_API_KEY", raising=False)
    tool = WebSearchTool(engine="youcom")
    tool._duckduckgo_search = MagicMock(
        return_value=("Fallback", [{"url": "https://example.com/fallback"}])
    )
    return tool


def response(status=200):
    return httpx.Response(
        status,
        request=httpx.Request("GET", "https://api.you.com/v1/agents/search"),
        json={
            "results": {
                "web": [
                    {
                        "title": "Actual result",
                        "url": "https://example.com/source",
                        "snippets": ["Snippet https://example.com/not-a-source"],
                    }
                ]
            },
        },
    )


def test_connection_error_recovers_once_and_keeps_actual_source(monkeypatch, search):
    get = MagicMock(side_effect=[httpx.ConnectError("TLS interrupted"), response()])
    monkeypatch.setattr(httpx, "get", get)
    result = search.execute(query="武汉景点")
    assert result.success and result.metadata["connection_attempts"] == 2
    assert [s["url"] for s in result.metadata["sources"]] == [
        "https://example.com/source"
    ]
    search._duckduckgo_search.assert_not_called()
    assert get.call_args.kwargs["timeout"].connect == 8
    assert "verify" not in get.call_args.kwargs


def test_connection_failure_is_bounded_and_fallback_is_marked(monkeypatch, search):
    get = MagicMock(side_effect=httpx.ConnectTimeout("unavailable"))
    monkeypatch.setattr(httpx, "get", get)
    result = search.execute(query="武汉景点")
    assert get.call_count == 2 and result.success
    assert result.metadata["degraded"] and result.metadata["fallback_from"] == "youcom"
    assert "unavailable" in result.metadata["fallback_reason"]
    assert result.metadata["sources"][0]["url"].endswith("/fallback")


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_http_errors_are_not_retried(monkeypatch, search, status):
    get = MagicMock(return_value=response(status))
    monkeypatch.setattr(httpx, "get", get)
    result = search.execute(query="武汉景点")
    assert get.call_count == 1
    assert result.metadata["degraded"]


def test_read_timeout_is_not_retried(monkeypatch, search):
    get = MagicMock(side_effect=httpx.ReadTimeout("slow response"))
    monkeypatch.setattr(httpx, "get", get)
    assert search.execute(query="武汉景点").metadata["degraded"]
    assert get.call_count == 1
