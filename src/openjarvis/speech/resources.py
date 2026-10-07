"""Cheap, local readiness checks for optional portable speech resources."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from openjarvis.core.paths import get_resource_dir

CHOICES = {
    "asr-zh": ("中文语音输入", "Chinese speech input", ["runtime-voice", "runtime-native", "asr-zh"]),
    "asr-en": ("英文语音输入", "English speech input", ["runtime-voice", "runtime-native", "speech-en"]),
    "tts": ("中文 / 英文语音播报", "Chinese / English speech output", ["runtime-voice", "runtime-native", "tts-kokoro"]),
    "piper": ("Piper 音色导入引擎", "Piper voice engine", ["runtime-piper"]),
    "clone": ("录音创建音色 · Qwen3-TTS", "Create voices from recordings · Qwen3-TTS", ["runtime-qwen", "model-qwen"]),
}


def installed(root: Path | None = None):
    root = root or get_resource_dir()
    from openjarvis.speech.jarvis_runtime import voice_runtime

    hf = root / "cache/huggingface/hub/models--hexgrad--Kokoro-82M"
    try:
        revision = (hf / "refs/main").read_text().strip()
        snapshot = hf / "snapshots" / revision
        kokoro = all((snapshot / p).is_file() for p in ("config.json", "kokoro-v1_0.pth", "voices/zm_yunjian.pt", "voices/bm_george.pt"))
    except OSError:
        kokoro = False
    python, _, _ = voice_runtime(root)
    return {
        "asr-zh": importlib.util.find_spec("sherpa_onnx") is not None and all((root / "models/speech/sensevoice" / p).is_file() for p in ("model.int8.onnx", "tokens.txt")),
        "asr-en": importlib.util.find_spec("faster_whisper") is not None and all((root / "models/speech/whisper-small.en" / p).is_file() for p in ("model.bin", "config.json", "tokenizer.json")),
        "tts": kokoro and importlib.util.find_spec("kokoro") is not None,
        "piper": importlib.util.find_spec("piper") is not None,
        "clone": python.is_file() and all((root / p).is_file() for p in ("scripts/qwen_tts_server.py", "scripts/qwen_voice_audio.py", "models/speech/qwen3-tts-0.6b-base/model.safetensors", "models/speech/qwen3-tts-0.6b-base/speech_tokenizer/model.safetensors")),
    }


def catalog():
    root = get_resource_dir()
    ready = installed(root)
    try:
        manifest = json.loads((root / "resources.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        manifest = {"packs": {}}
    packs = manifest["packs"]
    def size(name):
        pack = packs.get(name, {})
        return pack.get("bytes", sum(f["bytes"] for f in pack.get("files", [])))
    return {"choices": [{"id": key, "name": names[0], "name_en": names[1], "installed": ready[key], "available": all(p in packs for p in names[2]), "bytes": sum(size(p) for p in names[2])} for key, names in CHOICES.items()], "text_only": not any(ready[key] for key in ("asr-zh", "asr-en", "tts"))}
