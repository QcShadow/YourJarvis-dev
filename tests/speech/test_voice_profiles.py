"""Language, voice and persona are settings, not text-content heuristics."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.speech.profiles import (
    character_prompt,
    profile_backend,
    resolve_profile,
    synthesize_profile,
)


def test_english_only_voice_cannot_be_used_as_chinese_voice():
    with pytest.raises(ValueError, match="output language"):
        resolve_profile("piper-mcu-jarvis", "zh", "mcu-jarvis")
    assert resolve_profile("", "zh", "mcu-jarvis")["voice_id"] == "zm_yunjian"
    assert resolve_profile("", "en", "mcu-jarvis")["backend"] == "piper"


def test_voice_binding_is_not_portable_across_personas():
    with pytest.raises(ValueError, match="bound"):
        resolve_profile("piper-mcu-jarvis", "en", "jarvis-local")
    assert set(
        resolve_profile("jarvis-multilingual", "zh", "mcu-jarvis")["languages"]
    ) == {"zh", "en"}


def test_persona_and_output_language_prompt_preserve_real_capabilities():
    prompt = character_prompt("mcu-jarvis", "en")
    assert "British-English" in prompt and "Reply in English" in prompt
    assert "Only claim real actions after successful tool results" in prompt
    assert "not Paul Bettany" in prompt
    assert "Simplified Chinese" in character_prompt("jarvis-local", "zh")


def test_backend_voice_substitution_is_refused():
    backend = MagicMock()
    backend._voice_profile_lock = threading.Lock()
    backend.synthesize.return_value = SimpleNamespace(voice_id="jarvis-high")
    profile = resolve_profile("kokoro-zh-yunjian", "zh")
    with pytest.raises(RuntimeError, match="different voice"):
        synthesize_profile(backend, profile, "English words in 中文")
    assert backend.synthesize.call_args.kwargs["voice_id"] == "zm_yunjian"


@pytest.mark.anyio
async def test_profile_reuses_startup_warmup_instead_of_loading_again():
    backend = SimpleNamespace(backend_id="jarvis")
    pending = asyncio.create_task(asyncio.sleep(0.01, result=backend))
    app = SimpleNamespace(
        state=SimpleNamespace(
            tts_resolution_task=pending,
            config=SimpleNamespace(speech=SimpleNamespace(tts_backend="jarvis")),
        )
    )
    profile = resolve_profile("jarvis-multilingual", "zh", "mcu-jarvis")
    with patch("openjarvis.core.registry.TTSRegistry.get") as factory:
        selected = await profile_backend(app, profile)
        assert selected is backend
        factory.assert_not_called()
    assert hasattr(selected, "_voice_profile_lock")
