"""Named third-party OpenAI-compatible supplement with isolated model IDs."""

from __future__ import annotations

from openjarvis.core.config import ThirdPartyAPIEngineConfig
from openjarvis.engine.configured_api import ConfiguredAPIEngine, validate_endpoint

THIRD_PARTY_KEY = "THIRD_PARTY_API_KEY"
MODEL_PREFIX = "third-party/"


def validate_third_party_endpoint(url: str) -> str:
    url = url.strip().rstrip("/")
    if url.endswith("/v1/chat/completions"):
        url = url[: -len("/chat/completions")]
    return validate_endpoint(url)


def effective_config(config):
    cfg = config.engine.third_party_api
    # Older development settings continue working until saved through the new UI.
    legacy = config.engine.ustc
    if not cfg.host and legacy.enabled:
        return ThirdPartyAPIEngineConfig(
            enabled=True, name="中科大", host=legacy.host, models=list(legacy.models)
        )
    return cfg


def get_third_party_key(*, allow_legacy=False):
    from openjarvis.core.credentials import get_tool_credential

    return get_tool_credential("third_party_api", THIRD_PARTY_KEY) or (
        get_tool_credential("ustc", "USTC_API_KEY") if allow_legacy else None
    )


class ThirdPartyAPIEngine(ConfiguredAPIEngine):
    """Stable third-party/ IDs keep routing independent of the display name."""

    engine_id = "third_party_api"
    is_cloud = True

    def __init__(
        self, host: str, *, name="第三方 API", models=None, api_key=None, **kwargs
    ):
        super().__init__(
            host=validate_third_party_endpoint(host), api_key=api_key, **kwargs
        )
        self.name = name
        self._models = list(dict.fromkeys(models or []))

    def _resolve_model_id(self, model: str) -> str:
        if (
            not model.startswith(MODEL_PREFIX)
            or model[len(MODEL_PREFIX) :] not in self._models
        ):
            raise ValueError("Select a configured third-party API model.")
        return model[len(MODEL_PREFIX) :]

    def list_models(self) -> list[str]:
        return [f"{MODEL_PREFIX}{model}" for model in self._models]

    def health(self) -> bool:
        # The explicit test action checks inference; startup doesn't need a probe.
        return bool(self._api_key and self._models)


def with_third_party_api(engine, config, engine_name=""):
    """Attach inside security/telemetry wrappers without replacing the primary."""
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

    cfg = effective_config(config)
    if not cfg.enabled:
        return engine
    key = get_third_party_key(
        allow_legacy=config.engine.ustc.enabled and cfg.host == config.engine.ustc.host
    )
    if not key:
        return engine
    if isinstance(engine, InstrumentedEngine):
        engine._inner = with_third_party_api(engine._inner, config, engine_name)
        return engine
    if isinstance(engine, GuardrailsEngine):
        engine._engine = with_third_party_api(engine._engine, config, engine_name)
        return engine
    if isinstance(engine, MultiEngine):
        if any(name == "third_party_api" for name, _ in engine._engines):
            return engine
        entries = list(engine._engines)
    else:
        entries = [(engine_name or engine.engine_id, engine)]
    entries.append(
        (
            "third_party_api",
            ThirdPartyAPIEngine(
                host=cfg.host,
                name=cfg.name,
                models=cfg.models,
                api_key=key,
            ),
        )
    )
    return MultiEngine(entries)
