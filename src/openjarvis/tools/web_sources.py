"""Source records from retrieval payloads, never from model-written links."""

import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse


def safe_source_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
        ):
            return ""
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return value
    except ValueError:
        return ""


def source_authority(url: str) -> str:
    """Classify a domain as a trust *candidate*, never as verified fact."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return "general"
    # Include the registry domains themselves as well as their subdomains.
    # ``"gov.cn".endswith(".gov.cn")`` is false, so suffix-only checks would
    # silently classify an apex institutional domain as a general source.
    official_apex = {
        "gov",
        "gov.cn",
        "gov.uk",
        "gouv.fr",
        "go.jp",
        "go.kr",
        "gc.ca",
        "europa.eu",
    }
    academic_apex = {"edu", "edu.cn", "ac.uk", "ac.cn", "ac.jp"}
    institutional_apex = {"org", "org.cn"}
    if host in official_apex or host.endswith(
        (
            ".gov",
            ".gov.cn",
            ".gov.uk",
            ".gouv.fr",
            ".go.jp",
            ".go.kr",
            ".gc.ca",
            ".europa.eu",
        )
    ):
        return "official"
    if host in academic_apex or host.endswith(
        (".edu", ".edu.cn", ".ac.uk", ".ac.cn", ".ac.jp")
    ):
        return "academic"
    if host in institutional_apex or host.endswith((".org", ".org.cn")):
        return "institutional"
    return "general"


def source_records(items, *, url_key="url"):
    retrieved_at = datetime.now(timezone.utc).isoformat()
    records = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = safe_source_url(item.get(url_key))
        if not url or url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower().rstrip(".")
        records.append(
            {
                "url": url,
                "title": str(item.get("title") or url)[:300],
                "domain": domain,
                "authority": source_authority(url),
                "retrieved_at": retrieved_at,
            }
        )
        if len(records) == 20:
            break
    return records


def public_retrieval_metadata(result):
    """Do not expose internal executor policy/taint metadata to the client."""
    allowed = {
        "engine",
        "mode",
        "extractor",
        "url",
        "sources",
        "num_results",
        "retrieved_at",
        "degraded",
        "fallback_from",
        "fallback_reason",
        "fallback_error",
    }
    return {key: value for key, value in result.metadata.items() if key in allowed}
