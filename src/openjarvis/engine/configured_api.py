"""An explicit endpoint with a configured model, independent of cloud SDKs."""

from __future__ import annotations

from contextlib import aclosing
from urllib.parse import urlsplit

import httpx

from openjarvis.core.registry import EngineRegistry
from openjarvis.engine.openai_compat_engines import (
    OpenAICompatEngine,
    normalize_openai_base_url,
)


def validate_endpoint(url: str) -> str:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an http(s) URL without credentials, query or fragment.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Invalid endpoint port.") from exc
    return normalize_openai_base_url(url.strip())


@EngineRegistry.register("api")
class ConfiguredAPIEngine(OpenAICompatEngine):
    """No endpoint/model discovery beyond the endpoint chosen by the user."""

    engine_id = "api"

    def __init__(self, host: str, *, default_model: str = "", **kwargs):
        super().__init__(host=validate_endpoint(host), **kwargs)
        self._default_model = default_model

    def _resolve_model_id(self, model: str) -> str:
        # Provider names are opaque: never map them to an Ollama/catalog alias.
        return model

    def list_models(self) -> list[str]:
        # Many paid endpoints don't implement /models. Advertise only the
        # configured model; authentication/reachability is checked separately.
        return [self._default_model] if self._default_model else []

    @staticmethod
    def _api_options(kwargs):
        return {
            key: value
            for key, value in kwargs.items()
            if key not in {"num_ctx", "num_gpu", "think", "keep_alive"}
        }

    def generate(self, *args, **kwargs):
        return super().generate(*args, **self._api_options(kwargs))

    async def stream(self, *args, **kwargs):
        async with aclosing(
            super().stream(*args, **self._api_options(kwargs))
        ) as stream:
            async for token in stream:
                yield token

    async def stream_full(self, *args, **kwargs):
        async with aclosing(
            super().stream_full(*args, **self._api_options(kwargs))
        ) as stream:
            async for chunk in stream:
                yield chunk

    def health(self) -> bool:
        try:
            response = self._client.get("/v1/models", timeout=5)
            return response.status_code == 200 or (
                response.status_code in {404, 405} and bool(self._default_model)
            )
        except httpx.HTTPError:
            return False


def ensure_registered() -> None:
    if not EngineRegistry.contains("api"):
        EngineRegistry.register_value("api", ConfiguredAPIEngine)
