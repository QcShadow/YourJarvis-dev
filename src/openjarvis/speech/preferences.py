"""Persist microphone consent and options, never recordings or conversations."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from openjarvis.core.paths import get_config_dir


class VoicePreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    enabled: StrictBool
    options: dict | None = None

    @model_validator(mode="after")
    def enabled_needs_options(self):
        if self.enabled and self.options is None:
            raise ValueError("Enabled voice needs explicit saved options")
        return self


def preference_path() -> Path:
    override = os.environ.get("OPENJARVIS_VOICE_STATE_PATH")
    return Path(override) if override else get_config_dir() / "voice-preferences.json"


def load_preference() -> VoicePreference | None:
    path = preference_path()
    if not path.exists():
        return None  # Missing consent must never implicitly enable a microphone.
    if path.stat().st_size > 65536:
        raise ValueError("Voice preference file exceeds its size limit")
    return VoicePreference.model_validate_json(path.read_text(encoding="utf-8"))


def save_preference(*, enabled: bool, options: dict | None = None) -> None:
    path = preference_path()
    record = VoicePreference(enabled=enabled, options=options)
    payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    if len(payload.encode("utf-8")) > 65536:
        raise ValueError("Voice preference exceeds its size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".voice-pref-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
