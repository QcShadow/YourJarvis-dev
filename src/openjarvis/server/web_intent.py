"""Explicit current-information intents that must not become offline chat."""

import json
import re


def needs_web_search(prompt: str) -> bool:
    if re.search(
        r"不(?:要)?联网|不要搜索|离线回答|\b(?:offline|do not search)\b", prompt, re.I
    ):
        return False
    return bool(
        re.search(
            r"联网|上网|网上|网页|互联网|最新|实时|新闻|天气|票价|班次|航班|高铁|"
            r"(?:有什么|哪里|哪些).{0,10}(?:好玩|好吃|值得去)|旅游|旅行|游玩|景点|攻略|"
            r"开放时间|营业时间|门票|几点(?:开门|关门|开放|营业)|怎么预约|需要预约|"
            r"\b(?:web|internet|online|latest|news|weather|flights)\b|"
            r"opening hours|what time.{0,15}(?:open|close)|ticket price|"
            r"things to do|places to visit|travel itinerary",
            prompt,
            re.I,
        )
    )


def contextual_search_query(prompt, history):
    """Resolve short follow-up searches against explicit prior conversation.

    Never include memory/persona, and preserve executor taint/authorization.
    Detailed explanation alone does not force a fresh search.
    """
    query = prompt[:1000]
    contextual = re.match(
        r"^(?:那|它|这(?:个|些|里)|那里|第二个|第[一三四五]个|门票|票价|"
        r"开放时间|营业时间|几点|怎么预约|需要预约|多少钱|怎么去|"
        r"(?:what|when|how)\b|does it\b|is it\b|its\b|their\b)",
        prompt.strip(),
        re.I,
    )
    if not contextual or not history:
        return query
    topic = ""
    for message in reversed(history):
        for call in reversed(message.tool_calls or []):
            function = call.get("function") or {}
            if function.get("name") == "web_search":
                try:
                    arguments = function.get("arguments") or "{}"
                    params = (
                        json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments
                    )
                    if isinstance(params, dict) and isinstance(
                        params.get("query"), str
                    ):
                        topic = params["query"][:400]
                        break
                except (ValueError, TypeError):
                    pass
        if topic:
            break
    prior = next(
        (
            m.content[:300]
            for m in reversed(history)
            if m.role == "user"
            and m.content.strip().lower()
            not in {
                "具体说说",
                "展开说说",
                "详细一点",
                "简单一点",
                "tell me more",
                "elaborate",
            }
        ),
        "",
    )
    return "；".join(dict.fromkeys(part for part in (topic, prior, query) if part))[
        :1000
    ]


def preferred_search_query(prompt, history):
    """Add a narrow source hint while preserving the user's actual query.

    This is query guidance, not a claim that the provider will return an
    official page or that the returned content has been fact-checked.
    """
    query = contextual_search_query(prompt, history)
    if not re.search(r"[\u3400-\u9fff]", query):
        return query
    if re.search(r"天气|气温|降雨|台风|空气质量", prompt):
        hint = "官方气象 中文"
    elif re.search(r"新闻|消息|突发|政策|公告", prompt):
        hint = "官方来源 中文"
    elif re.search(
        r"旅游|旅行|游玩|景点|攻略|门票|票价|开放时间|营业时间|预约|几点",
        prompt,
    ):
        hint = "官网 官方 中文"
    else:
        hint = "官方来源 中文"
    available = max(0, 1000 - len(hint) - 1)
    return f"{query[:available]} {hint}" if available else hint[:1000]
