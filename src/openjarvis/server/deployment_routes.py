"""Local configuration management for the delivered Windows/browser app."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from time import time_ns
from typing import Literal
from urllib.parse import urlsplit

import httpx
import tomlkit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from openjarvis.core.deployment import MODEL_PRESETS, VOICE_PRESETS
from openjarvis.core.paths import get_config_path
from openjarvis.engine.configured_api import validate_endpoint
from openjarvis.engine.third_party_api import (
    THIRD_PARTY_KEY,
    get_third_party_key,
    validate_third_party_endpoint,
)
from openjarvis.security.file_utils import secure_write_text

router = APIRouter(prefix="/v1/deployment", tags=["deployment"])
_LOCK = threading.Lock()


class ThirdPartyAPISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    name: str = Field(default="第三方 API", max_length=80)
    base_url: str = Field(default="", max_length=2048)
    models: list[str] = Field(default_factory=list, max_length=200)
    api_key: SecretStr | None = None
    clear_api_key: bool = False


def _third_party_values(body: ThirdPartyAPISettings):
    if not body.name.strip() or any(ord(c) < 32 for c in body.name):
        raise HTTPException(422, "Enter a display name for this API.")
    try:
        url = validate_third_party_endpoint(body.base_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    models = list(dict.fromkeys(model.strip() for model in body.models))
    if not models or any(
        not model
        or len(model) > 256
        or model.startswith("third-party/")
        or any(ord(c) < 33 for c in model)
        for model in models
    ):
        raise HTTPException(
            422, "Enter the platform's exact model IDs, without third-party/."
        )
    if body.clear_api_key and body.api_key:
        raise HTTPException(422, "Choose either a new key or clear the saved key.")
    saved = _saved_third_party()
    same_endpoint = False
    if saved.get("host"):
        same_endpoint = url == validate_third_party_endpoint(saved["host"])
    key = (
        body.api_key.get_secret_value().strip()
        if body.api_key
        else (
            get_third_party_key(allow_legacy=saved.get("legacy", False))
            if same_endpoint
            else None
        )
    )
    if body.clear_api_key:
        key = None
    if key and any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(422, "Invalid API key characters.")
    return url, models, key


def _saved_third_party():
    path = config_path()
    saved = tomlkit.parse(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    engines = saved.get("engine", {})
    if "third_party_api" in engines:
        return engines["third_party_api"]
    legacy = engines.get("ustc", {})
    if legacy:
        return {**legacy, "name": "中科大", "legacy": True}
    return {}


@router.get("/third-party-api")
async def third_party_settings(request: Request):
    require_local(request)
    cfg = _saved_third_party()
    return {
        "enabled": cfg.get("enabled", False),
        "name": cfg.get("name", "第三方 API"),
        "base_url": cfg.get("host", ""),
        "models": cfg.get("models", []),
        "has_api_key": bool(get_third_party_key(allow_legacy=cfg.get("legacy", False))),
    }


@router.post("/third-party-api")
async def save_third_party_settings(body: ThirdPartyAPISettings, request: Request):
    require_local(request)
    url, models, key = _third_party_values(body)
    if body.enabled and not key:
        raise HTTPException(
            422, "Enter the API key for this endpoint before enabling it."
        )
    from openjarvis.core.credentials import delete_credential, save_credential

    path = config_path()
    with _LOCK:
        original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        doc = tomlkit.parse(original)
        doc.setdefault("engine", tomlkit.table())["third_party_api"] = {
            "enabled": body.enabled,
            "name": body.name.strip(),
            "host": url,
            "models": models,
        }
        if "ustc" in doc["engine"]:
            doc["engine"]["ustc"]["enabled"] = False
        if original:
            secure_write_text(
                path.with_name(f"config.before-third-party-api-{time_ns()}.toml"),
                original,
            )
        if key:
            save_credential("third_party_api", THIRD_PARTY_KEY, key)
        else:
            delete_credential("third_party_api", THIRD_PARTY_KEY)
        if body.clear_api_key:
            delete_credential("ustc", "USTC_API_KEY")
        secure_write_text(path, tomlkit.dumps(doc))
    return {"saved": True, "restart_required": True}


@router.post("/third-party-api/test")
async def test_third_party_connection(body: ThirdPartyAPISettings, request: Request):
    """Run one short inference with the supplied/saved key; do not persist it."""
    require_local(request)
    url, models, key = _third_party_values(body)
    if not key:
        raise HTTPException(422, "Enter the API key for this endpoint first.")
    available = []
    try:
        async with httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": models[0],
                    "messages": [{"role": "user", "content": "你好"}],
                    "max_tokens": 64,
                    "stream": False,
                },
            )
            if not response.is_success:
                # Only report status, never echo a third-party body or key.
                raise HTTPException(
                    502,
                    f"Third-party API HTTP {response.status_code}: "
                    "check key, model access and quota.",
                )
            result = response.json()
            choices = result.get("choices") or []
            content = choices[0].get("message", {}).get("content") if choices else None
            if (
                result.get("error")
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise HTTPException(
                    502,
                    "Third-party API returned no answer. "
                    "Check the model ID or try a chat model.",
                )
            # Some gateways don't offer /models. A successful chat still works.
            try:
                catalog = await client.get("/v1/models", timeout=10)
                if catalog.is_success:
                    available = [
                        row["id"]
                        for row in catalog.json().get("data", [])
                        if isinstance(row, dict) and isinstance(row.get("id"), str)
                    ]
            except (httpx.HTTPError, ValueError, TypeError):
                pass
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, "Cannot connect to Third-party API. Check network access and retry."
        ) from exc
    except (ValueError, TypeError, AttributeError, IndexError) as exc:
        raise HTTPException(
            502, "Third-party API returned an invalid OpenAI-compatible response."
        ) from exc
    return {
        "ok": True,
        "model": models[0],
        "reply": content[:1000],
        "available_models": available,
    }


def config_path() -> Path:
    return (
        Path(os.environ["OPENJARVIS_CONFIG"])
        if os.environ.get("OPENJARVIS_CONFIG")
        else get_config_path()
    )


def require_local(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Configure models from the host computer only.")
    if request.headers.get("forwarded") or request.headers.get("x-forwarded-for"):
        raise HTTPException(403, "Configuration cannot be changed through a proxy.")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(
                403, "A remote website cannot change your model settings."
            )
        if parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
            raise HTTPException(
                403, "Configuration requires the same-origin local app."
            )


class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["lite", "balanced", "custom-local", "api", "remote-host"]
    model: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=2048)
    api_key: SecretStr | None = None
    clear_api_key: bool = False


@router.get("/bootstrap")
async def bootstrap(request: Request):
    """Fresh browser preferences follow the recipient's saved setup preset."""
    require_local(request)
    path = config_path()
    doc = tomlkit.parse(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    deployment = doc.get("deployment", {})
    if not deployment.get("preset_version"):
        return {"configured": False}
    profile = deployment.get("profile", "custom-local")
    voice = deployment.get("voice", "zh")
    speech = VOICE_PRESETS.get(voice, VOICE_PRESETS["zh"])
    preset = MODEL_PRESETS.get(profile, MODEL_PRESETS["custom-local"])
    model = doc.get("intelligence", {}).get("default_model", "")
    result = {
        "configured": True,
        "settings": {
            "defaultModel": model,
            "defaultAgent": doc.get("agent", {}).get("default_agent", "simple"),
            "maxTokens": preset["max_tokens"],
            "automaticModelRouting": profile not in {"lite", "api", "remote-host"},
            "recognitionLanguage": speech["language"],
            "outputLanguage": "recognition",
            "speechEnabled": voice != "text",
            "voiceOutputEnabled": voice != "text",
            "voiceAutoplay": voice != "text",
            "wakeWordEnabled": bool(deployment.get("full_features")),
            "voiceId": speech["voice_id"],
            "voiceProfileZh": "kokoro-zh-xiaoxiao"
            if voice == "zh-female"
            else "kokoro-zh-yunjian",
            "voiceProfileEn": "kokoro-en-george",
        },
    }
    if deployment.get("voice_profile") == "jarvis-multilingual":
        result["settings"].update(
            {
                "characterId": "mcu-jarvis",
                "outputLanguage": "zh",
                "voiceId": "jarvis-high",
                "voiceProfileZh": "jarvis-multilingual",
                "voiceProfileEn": "piper-mcu-jarvis",
            }
        )
    return result


@router.get("/settings")
async def settings(request: Request):
    require_local(request)
    from openjarvis.core.credentials import get_tool_credential

    cfg = request.app.state.config
    if cfg is None:
        raise HTTPException(503, "Configuration is unavailable.")
    path = config_path()
    saved = tomlkit.parse(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    engine = saved.get("engine", {}).get("default", cfg.engine.default)
    model = saved.get("intelligence", {}).get(
        "default_model", cfg.intelligence.default_model
    )
    base_url = saved.get("engine", {}).get(engine, {}).get("host", "") or (
        cfg.engine.api.host if engine == "api" else cfg.engine.ollama.host
    )
    return {
        "engine": engine,
        "profile": saved.get("deployment", {}).get(
            "profile", "api" if engine == "api" else "custom-local"
        ),
        "model": model,
        "base_url": base_url,
        "restart_required": engine != cfg.engine.default
        or model != cfg.intelligence.default_model
        or base_url
        != (cfg.engine.api.host if engine == "api" else cfg.engine.ollama.host),
        "has_api_key": bool(get_tool_credential("llm", "JARVIS_LLM_API_KEY")),
        "ram_gb": cfg.hardware.ram_gb,
        "presets": MODEL_PRESETS,
        "local_base_url": os.environ.get(
            "JARVIS_LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"
        ),
        "portable_client": os.environ.get("JARVIS_PORTABLE_CLIENT") == "1",
    }


@router.post("/settings")
async def save_settings(body: ConnectionSettings, request: Request):
    require_local(request)
    model = body.model.strip() or MODEL_PRESETS[body.profile]["model"]
    if not model or any(ord(c) < 32 for c in model):
        raise HTTPException(422, "Fill in the full model ID.")
    if body.clear_api_key and body.api_key:
        raise HTTPException(422, "Choose either a new key or clear the saved key.")
    try:
        url = (
            validate_endpoint(body.base_url)
            if body.profile in {"api", "remote-host"}
            else (
                validate_endpoint(body.base_url)
                if body.base_url
                else "http://127.0.0.1:11434"
            )
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    from openjarvis.core.credentials import delete_credential, save_credential

    path = config_path()
    # Disk I/O is short and serialized. The active engine is deliberately left
    # running; restart applies the new configuration without interrupting chats.
    with _LOCK:
        original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        doc = tomlkit.parse(original)
        engine = doc.setdefault("engine", tomlkit.table())
        engine["default"] = (
            "api" if body.profile in {"api", "remote-host"} else "ollama"
        )
        if body.profile in {"api", "remote-host"}:
            engine["api"] = {"host": url, "api_key_env": "JARVIS_LLM_API_KEY"}
        else:
            preset = MODEL_PRESETS[body.profile]
            engine["ollama"] = {
                "host": url,
                "num_ctx": preset["num_ctx"],
                "num_gpu": preset["num_gpu"],
            }
        intelligence = doc.setdefault("intelligence", tomlkit.table())
        for key in ("default_model", "model_chat", "model_long", "fallback_model"):
            intelligence[key] = model
        intelligence["max_tokens"] = MODEL_PRESETS[body.profile]["max_tokens"]
        doc.setdefault("server", tomlkit.table())["model"] = model
        doc.setdefault("deployment", tomlkit.table())["profile"] = body.profile
        if original:
            secure_write_text(
                path.with_name(f"config.before-model-{time_ns()}.toml"), original
            )
        if body.api_key and body.api_key.get_secret_value().strip():
            save_credential(
                "llm", "JARVIS_LLM_API_KEY", body.api_key.get_secret_value()
            )
        elif body.clear_api_key:
            delete_credential("llm", "JARVIS_LLM_API_KEY")
        secure_write_text(path, tomlkit.dumps(doc))
    return {"saved": True, "restart_required": True, "model": model}
