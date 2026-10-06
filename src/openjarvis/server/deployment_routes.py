"""Local configuration management for the delivered Windows/browser app."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from time import time_ns
from typing import Literal
from urllib.parse import urlsplit

import tomlkit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from openjarvis.core.deployment import MODEL_PRESETS, VOICE_PRESETS
from openjarvis.core.paths import get_config_path
from openjarvis.engine.configured_api import validate_endpoint
from openjarvis.security.file_utils import secure_write_text

router = APIRouter(prefix="/v1/deployment", tags=["deployment"])
_LOCK = threading.Lock()


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
        result["settings"].update({
            "characterId": "mcu-jarvis",
            "outputLanguage": "zh",
            "voiceId": "jarvis-high",
            "voiceProfileZh": "jarvis-multilingual",
            "voiceProfileEn": "piper-mcu-jarvis",
        })
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
