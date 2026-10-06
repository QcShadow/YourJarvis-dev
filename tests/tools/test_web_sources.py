"""Retrieval provenance must come from payloads, not model-written claims."""

from datetime import datetime

import pytest

from openjarvis.core.types import ToolResult
from openjarvis.tools.web_sources import (
    public_retrieval_metadata,
    safe_source_url,
    source_authority,
    source_records,
)


@pytest.mark.parametrize(
    "url",
    [
        None,
        12,
        "",
        "javascript:alert(1)",
        "file:///D:/Jarvis/config.toml",
        "https://u:p@example.com",
        "http://localhost",
        "http://x.localhost",
        "http://device.local",
        "http://service.internal",
        "http://127.0.0.1",
        "http://10.0.0.2",
        "http://[::1]",
        "https://[broken",
        "https://" + "a" * 2048,
    ],
)
def test_source_urls_exclude_private_and_non_web_targets(url):
    assert safe_source_url(url) == ""


def test_source_records_are_bounded_deduplicated_payload_records():
    items = [None, "bad", {"link": "http://localhost"}]
    items += [{"link": "https://example.com/1", "title": "a" * 400}] * 2
    items += [{"link": f"https://example.com/{i}"} for i in range(2, 30)]
    sources = source_records(items, url_key="link")
    assert len(sources) == 20
    assert len(sources[0]["title"]) == 300
    assert sources[1]["title"] == sources[1]["url"]
    assert (
        datetime.fromisoformat(sources[0]["retrieved_at"]).utcoffset().total_seconds()
        == 0
    )
    assert sources[0]["domain"] == "example.com"
    assert sources[0]["authority"] == "general"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.gov.cn/policy", "official"),
        ("https://gov.cn/policy", "official"),
        ("https://beijing.gov.cn/notice", "official"),
        ("https://example.edu.cn/paper", "academic"),
        ("https://edu.cn/catalog", "academic"),
        ("https://example.org/project", "institutional"),
        ("https://org.cn/project", "institutional"),
        ("https://news.example.com/story", "general"),
        ("HTTPS://EXAMPLE.GOV.CN./notice", "official"),
        ("https://example.gov.cn.evil.example/story", "general"),
    ],
)
def test_source_authority_is_conservative_domain_signal(url, expected):
    assert source_authority(url) == expected


def test_public_metadata_does_not_leak_executor_state_or_api_credentials():
    result = ToolResult(
        tool_name="web_search",
        content="",
        success=True,
        metadata={
            "engine": "youcom",
            "sources": [{"url": "https://example.com"}],
            "degraded": True,
            "fallback_reason": "network failure",
            "fallback_error": "fallback network failure",
            "api_key": "secret",
            "taint": "private",
            "policy": {"internal": True},
        },
    )
    assert set(public_retrieval_metadata(result)) == {
        "engine",
        "sources",
        "degraded",
        "fallback_reason",
        "fallback_error",
    }
