"""Explicit voice/language/character bindings; never guess from output text."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from openjarvis.core.paths import get_resource_dir

CHARACTERS = {
    "jarvis-local": {
        "id": "jarvis-local",
        "name": "Jarvis · 本地助手",
        "default_language": "zh",
        "description": "冷静、直接，简短自然；避免客套和反复确认。",
        "style": (
            "Calm, concise and practical. Speak naturally, normally in one or "
            "two sentences. No ceremonial address, repetitive confirmations "
            "or filler. Give the useful result first."
        ),
        "default_voices": {"zh": "kokoro-zh-yunjian", "en": "kokoro-en-george"},
        "sources": [],
    },
    "mcu-jarvis": {
        "id": "mcu-jarvis",
        "name": "MCU Jarvis · English",
        "default_language": "en",
        "description": (
            "电影风格：沉稳的英式表达、克制的幽默、主动报告关键结果。"
            "不是官方授权角色服务。"
        ),
        "style": (
            "Use a measured British-English assistant style inspired by MCU "
            "Jarvis: composed, precise, quietly resourceful, with restrained "
            "dry wit only when useful. Prefer a crisp acknowledgement and "
            "the result, usually one or two conversational sentences. Avoid "
            "breathless enthusiasm, generic chatbot lists and repeated "
            "'shall I proceed' questions. Do not call the user Tony or sir "
            "unless they explicitly request it. You are a local assistant "
            "with a fictional style, not Paul Bettany, not Marvel's official "
            "service, and have no fictional suit or Stark-system access. "
            "Only claim real actions after successful tool results."
        ),
        "default_voices": {"en": "piper-mcu-jarvis", "zh": "kokoro-zh-yunjian"},
        "sources": [
            "https://d23.com/wanda-maximoff-and-visions-mcu-origins-explained/",
            "https://huggingface.co/jgkawell/jarvis",
        ],
    },
}

VOICES = {
    "kokoro-zh-yunjian": {
        "id": "kokoro-zh-yunjian",
        "name": "云健 · 沉稳男声",
        "backend": "kokoro",
        "voice_id": "zm_yunjian",
        "languages": ["zh"],
        "characters": ["jarvis-local", "mcu-jarvis"],
        "experimental": False,
    },
    "kokoro-zh-yunxi": {
        "id": "kokoro-zh-yunxi",
        "name": "云希 · 中文男声",
        "backend": "kokoro",
        "voice_id": "zm_yunxi",
        "languages": ["zh"],
        "characters": ["jarvis-local", "mcu-jarvis"],
        "experimental": False,
    },
    "kokoro-zh-xiaoxiao": {
        "id": "kokoro-zh-xiaoxiao",
        "name": "晓晓 · 中文女声",
        "backend": "kokoro",
        "voice_id": "zf_xiaoxiao",
        "languages": ["zh"],
        "characters": ["jarvis-local", "mcu-jarvis"],
        "experimental": False,
    },
    "kokoro-en-george": {
        "id": "kokoro-en-george",
        "name": "George · British English",
        "backend": "kokoro",
        "voice_id": "bm_george",
        "languages": ["en"],
        "characters": ["jarvis-local", "mcu-jarvis"],
        "experimental": False,
    },
    "piper-mcu-jarvis": {
        "id": "piper-mcu-jarvis",
        "name": "MCU Jarvis · English (Piper)",
        "backend": "piper",
        "voice_id": "jarvis-high",
        "languages": ["en"],
        "characters": ["mcu-jarvis"],
        "experimental": False,
        "source": "https://huggingface.co/jgkawell/jarvis",
        "note": "Community voice emulation, not an official actor recording.",
    },
    "jarvis-multilingual": {
        "id": "jarvis-multilingual",
        "name": "JARVIS high · 中文跨语言",
        "backend": "jarvis",
        "voice_id": "jarvis-high",
        "languages": ["zh", "en"],
        "characters": ["mcu-jarvis"],
        "experimental": True,
        "note": (
            "Chinese synthesis uses the separate Qwen-TTS runtime; "
            "the CUDA runtime supports streaming after warmup."
        ),
    },
}


def resolve_profile(profile_id, language, character_id="jarvis-local"):
    if character_id not in CHARACTERS:
        raise ValueError("Unknown character profile")
    if language not in {"zh", "en"}:
        raise ValueError("Output language must be zh or en")
    profile_id = profile_id or CHARACTERS[character_id]["default_voices"][language]
    profile = VOICES.get(profile_id)
    if profile is None:
        raise ValueError("Unknown voice profile")
    if language not in profile["languages"]:
        raise ValueError("The selected voice does not support the output language")
    if character_id not in profile["characters"]:
        raise ValueError("The selected voice is not bound to this character")
    return profile


def character_prompt(character_id, language):
    if not character_id and not language:
        return ""
    character = CHARACTERS.get(character_id or "jarvis-local")
    if character is None:
        raise ValueError("Unknown character profile")
    language = language or character["default_language"]
    instruction = (
        "Reply in Simplified Chinese, even when input is English; keep code, "
        "names and quoted text unchanged. Do not switch your spoken response "
        "language based on the input. Address the user with 你, never 您 or 先生."
        if language == "zh"
        else "Reply in English, even when input is Chinese; keep code, names "
        "and quoted text unchanged. Do not switch your spoken response "
        "language based on the input."
    )
    return (
        "Character and response-language settings:\n"
        + character["style"]
        + "\n"
        + instruction
    )


def catalog():
    from openjarvis.speech.jarvis_runtime import voice_runtime

    root = get_resource_dir()
    voices = []
    for value in VOICES.values():
        available = value["backend"] == "kokoro"
        if value["backend"] == "piper":
            model = root / "models/piper/jarvis-high/jarvis-high.onnx"
            available = model.is_file() and Path(str(model) + ".json").is_file()
        if value["backend"] == "jarvis":
            python, _engine, device = voice_runtime(root)
            available = python.is_file() and all(
                (root / name).is_file()
                for name in (
                    "scripts/qwen_tts_server.py",
                    "scripts/qwen_voice_audio.py",
                    "models/speech/qwen3-tts-0.6b-base/model.safetensors",
                    "models/speech/qwen3-tts-0.6b-base/speech_tokenizer/model.safetensors",
                    "models/piper/jarvis-high/reference.wav",
                    "models/piper/jarvis-high/reference.txt",
                    "models/piper/jarvis-high/jarvis-high.onnx",
                    "models/piper/jarvis-high/jarvis-high.onnx.json",
                )
            )
            if available and device == "cpu":
                value = {**value, "note": (
                    "内置中文跨语言音源，按需加载。CPU 合成可能需要较长等待；"
                    "建议 16 GB 内存起，24 GB 更舒适。可切回云健或晓晓。"
                )}
        voices.append({**value, "installed": available})
    return {"characters": list(CHARACTERS.values()), "voices": voices}


async def profile_backend(app, profile):
    """Coalesce loads per backend, with no silent voice/backend fallback."""
    import openjarvis.speech  # noqa: F401
    from openjarvis.core.registry import TTSRegistry

    if not hasattr(app.state, "voice_profile_loads"):
        app.state.voice_profile_loads = {}
    tasks = app.state.voice_profile_loads
    key = profile["backend"]
    task = tasks.get(key)
    if task is None:

        def load():
            kwargs = {"device": "cpu"} if key == "kokoro" else {}
            if key == "piper":
                kwargs = {"strict_voice": True}
            backend = TTSRegistry.get(key)(**kwargs)
            if not backend.health():
                raise RuntimeError(f"Selected voice backend '{key}' is unavailable")
            backend._voice_profile_lock = threading.Lock()
            return backend

        async def load_or_reuse():
            # Startup health already warms the default backend. Sharing that
            # instance avoids loading Piper again on the first profile request.
            pending = getattr(app.state, "tts_resolution_task", None)
            backend = getattr(app.state, "tts_backend", None)
            config = getattr(app.state, "config", None)
            speech = getattr(config, "speech", None)
            if pending is not None and getattr(speech, "tts_backend", None) == key:
                backend = await asyncio.shield(pending)
            if backend is not None and backend.backend_id == key:
                if not hasattr(backend, "_voice_profile_lock"):
                    backend._voice_profile_lock = threading.Lock()
                return backend
            return await asyncio.to_thread(load)

        task = asyncio.create_task(load_or_reuse())
        tasks[key] = task
    try:
        return await asyncio.shield(task)
    except Exception:
        if task.done() and tasks.get(key) is task:
            tasks.pop(key, None)
        raise


def synthesize_profile(backend, profile, text, **kwargs):
    kwargs["voice_id"] = profile["voice_id"]
    with backend._voice_profile_lock:
        result = backend.synthesize(text, **kwargs)
    if result.voice_id and result.voice_id != profile["voice_id"]:
        raise RuntimeError("Voice backend returned a different voice; playback refused")
    return result
