"""Resolve the isolated JARVIS voice interpreter without virtualenv relocation."""

from __future__ import annotations

import json
from pathlib import Path


def voice_runtime(root: Path) -> tuple[Path, str, str]:
    settings_path = root / "runtimes/qwen-tts/voice_settings.json"
    settings = (
        json.loads(settings_path.read_text(encoding="utf-8-sig"))
        if settings_path.is_file()
        else {}
    )
    engine = settings.get("engine", "standard")
    device = settings.get("device", "auto")
    if engine not in {"standard", "faster"} or device not in {"auto", "cpu", "cuda:0"}:
        raise ValueError("Invalid JARVIS voice engine or device")
    runtime = root / "runtimes" / ("qwen-fast" if engine == "faster" else "qwen-tts")
    portable = runtime / "python/python.exe"
    python = portable if portable.is_file() else runtime / ".venv/Scripts/python.exe"
    return python, engine, device
