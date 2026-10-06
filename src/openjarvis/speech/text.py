"""Recognition language controls writing conventions, not translation."""

from functools import lru_cache


@lru_cache(maxsize=1)
def _simplifier():
    from opencc import OpenCC

    return OpenCC("t2s")


def normalize_transcript(text: str, language: str | None) -> str:
    if language and language.lower().replace("_", "-").split("-")[0] == "zh":
        return _simplifier().convert(text)
    return text
