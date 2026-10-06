"""A language switch must select a different actual recognition backend."""

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.speech._stubs import TranscriptionResult
from openjarvis.speech.language_routed import LanguageRoutedSpeechBackend


def make_backend(tmp_path):
    return LanguageRoutedSpeechBackend(
        chinese_model=str(tmp_path / "zh"), english_model=str(tmp_path / "en")
    )


def test_language_selection_routes_to_independent_models(tmp_path):
    backend = make_backend(tmp_path)
    chinese, english = MagicMock(), MagicMock()
    backend.chinese, backend.english = chinese, english
    chinese.transcribe.return_value = TranscriptionResult("中文", language="zh")
    english.transcribe.return_value = TranscriptionResult("English", language="en")
    assert backend.transcribe(b"audio").text == "中文"
    assert backend.transcribe(b"audio", language="zh-CN").text == "中文"
    assert backend.transcribe(b"audio", language="en-US").text == "English"
    assert chinese.transcribe.call_args.kwargs["language"] == "zh"
    assert english.transcribe.call_args.kwargs["language"] == "en"
    assert english.transcribe.call_count == 1


def test_english_model_is_cpu_int8_and_not_multilingual(tmp_path):
    backend = LanguageRoutedSpeechBackend(chinese_model=str(tmp_path))
    assert backend.english._model_size == "small.en"
    assert backend.english._device == "cpu"
    assert backend.english._compute_type == "int8"


def test_unsupported_language_is_not_silently_changed(tmp_path):
    backend = make_backend(tmp_path)
    with pytest.raises(ValueError, match="Simplified Chinese or English"):
        backend.transcribe(b"audio", language="fr")


def test_health_and_model_profiles_do_not_load_unused_english_model(tmp_path):
    backend = make_backend(tmp_path)
    with (
        patch.object(backend.chinese, "health", return_value=True),
        patch.object(backend.english, "health") as english,
    ):
        assert backend.health()
    english.assert_not_called()
    assert backend.profiles()["en"]["model"] == "Whisper small.en INT8"
    assert not backend.profiles()["zh"]["available"]
