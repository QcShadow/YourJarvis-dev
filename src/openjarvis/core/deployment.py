"""Portable presets. No owner-specific paths, memories or credentials."""

from __future__ import annotations

import re
from pathlib import Path

import tomlkit

from openjarvis.security.file_utils import secure_write_text

MODEL_PRESETS = {
    "lite": {
        "model": "qwen2.5:0.5b",
        "download_gb": 0.40,
        "ram_gb": 4,
        "recommended_ram_gb": 8,
        "vram_gb": 0,
        "num_ctx": 2048,
        "num_gpu": 0,
        "max_tokens": 256,
        "description": "中文短对话保底，CPU 可用；不适合复杂推理和自动执行工具。",
        "source": "https://ollama.com/library/qwen2.5:0.5b",
    },
    "balanced": {
        "model": "qwen3:1.7b",
        "download_gb": 1.4,
        "ram_gb": 8,
        "recommended_ram_gb": 16,
        "vram_gb": 0,
        "num_ctx": 4096,
        "num_gpu": -1,
        "max_tokens": 512,
        "description": "更好的中文聊天；CPU 可用，速度随硬件变化。",
        "source": "https://ollama.com/library/qwen3:1.7b",
    },
    "custom-local": {
        "model": "",
        "num_ctx": 4096,
        "num_gpu": -1,
        "max_tokens": 1024,
        "description": "使用你已在 Ollama 安装的模型，填写完整模型名。",
    },
    "api": {
        "model": "",
        "max_tokens": 1024,
        "description": (
            "自填 OpenAI 兼容地址、模型 ID 和密钥；也支持 LM Studio 等本地服务。"
        ),
    },
    "remote-host": {
        "model": "host-model",
        "max_tokens": 2048,
        "description": "连接 JARVIS 主机的共享推理入口；界面、工具和记忆仍在本机运行。",
    },
}

VOICE_PRESETS = {
    "zh": {
        "backend": "kokoro",
        "voice_id": "zm_yunjian",
        "language": "zh",
        "description": (
            "中文 SenseVoice INT8 识别 + Kokoro 云健，CPU 优先，建议整机 8 GB 起。"
        ),
    },
    "zh-female": {
        "backend": "kokoro",
        "voice_id": "zf_xiaoxiao",
        "language": "zh",
        "description": "中文 SenseVoice INT8 识别 + Kokoro 晓晓，CPU 优先。",
    },
    "en": {
        "backend": "kokoro",
        "voice_id": "bm_george",
        "language": "en",
        "description": (
            "Whisper small.en INT8 识别 + Kokoro 英式 George；额外下载英语识别包。"
        ),
    },
    "text": {
        "backend": "kokoro",
        "voice_id": "zm_yunjian",
        "language": "zh",
        "description": "先用文字聊天，声音仍可在设置中启用；无需先安装语音权重。",
    },
}

DEFAULT_PROMPT = (
    "你是 JARVIS，用户配置的 AI 助手。默认用简体中文，回答自然、直接、简洁。"
    "不称呼用户为先生。缺少信息时如实说明，不编造工具执行结果。"
    "除非用户要求详细说明，通常回答一至三句话。"
)


def configuration_text(
    root: Path,
    *,
    profile: str = "lite",
    model: str = "",
    base_url: str = "",
    api_key_env: str = "JARVIS_LLM_API_KEY",
    voice: str = "zh",
    full_features: bool = False,
) -> str:
    """Render a fresh configuration; deliberately never read the owner's config."""
    if profile not in MODEL_PRESETS or voice not in VOICE_PRESETS:
        raise ValueError("Unknown model or voice preset.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError("Invalid API key environment variable name.")
    preset, speech = MODEL_PRESETS[profile], VOICE_PRESETS[voice]
    model = model.strip() or preset["model"]
    if not model or len(model) > 256 or any(ord(c) < 32 for c in model):
        raise ValueError("Fill in a valid model ID (maximum 256 characters).")
    engine = "api" if profile in {"api", "remote-host"} else "ollama"
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Generated portable preset; configure your own model/API."))
    doc["engine"] = {"default": engine}
    if engine == "api":
        from openjarvis.engine.configured_api import validate_endpoint

        doc["engine"]["api"] = {
            "host": validate_endpoint(base_url),
            "api_key_env": api_key_env,
        }
    else:
        doc["engine"]["ollama"] = {
            "host": base_url.strip() or "http://127.0.0.1:11434",
            "num_ctx": preset["num_ctx"],
            "num_gpu": preset["num_gpu"],
        }
    doc["intelligence"] = {
        "default_model": model,
        "model_chat": model,
        "model_long": model,
        "fallback_model": model,
        "temperature": 0.3,
        "max_tokens": preset["max_tokens"],
    }
    doc["agent"] = {
        "default_agent": "orchestrator" if full_features else "simple",
        "max_turns": 10 if full_features else 3,
        "context_from_memory": full_features,
        "default_system_prompt": DEFAULT_PROMPT,
    }
    doc["memory"] = {"enabled": full_features}
    doc["tools"] = {
        "enabled": [
            "calculator",
            "system_time",
            "list_files",
            "file_read",
            "browser_open",
            "web_search",
            "memory_manage",
            "memory_store",
            "memory_retrieve",
            "memory_search",
            "memory_index",
            "shell_exec",
            "code_interpreter",
        ]
        if full_features
        else ["calculator"]
    }
    doc["speech"] = {
        "backend": "language-routed",
        "language": speech["language"],
        "device": "cpu",
        "compute_type": "int8",
        "chinese_model": str(root / "models/speech/sensevoice"),
        "english_model": str(root / "models/speech/whisper-small.en"),
        "tts_backend": speech["backend"],
        "voice_id": speech["voice_id"],
        "voice_speed": 1.0,
    }
    doc["server"] = {"host": "127.0.0.1", "port": 8000, "model": model}
    doc["analytics"] = {"enabled": False}
    doc["deployment"] = {
        "profile": profile,
        "voice": voice,
        "preset_version": 2 if full_features else 1,
        "full_features": full_features,
    }
    if full_features:
        doc["deployment"]["resource_root"] = str(root)
    return tomlkit.dumps(doc)


def write_configuration(root: Path, *, replace: bool = False, **options) -> Path:
    """Refuse accidental replacement; preserve an existing config on reconfigure."""
    path = root / "config.toml"
    if path.exists() and not replace:
        raise FileExistsError(
            "Configuration exists; use --replace to save a backup and replace it."
        )
    content = configuration_text(root, **options)
    if path.exists():
        from time import time_ns

        secure_write_text(
            path.with_name(f"config.before-setup-{time_ns()}.toml"),
            path.read_text(encoding="utf-8-sig"),
        )
    return secure_write_text(path, content)
