"""Check bilingual routing and real WAV framing without downloading weights."""

from __future__ import annotations

import io
import os
import sys
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openjarvis.speech.piper_tts import PiperTTSBackend
from openjarvis.speech.tts import TTSResult


def test_english_uses_jarvis_despite_saved_chinese_voice(tmp_path):
    calls = []

    class Voice:
        config = SimpleNamespace(length_scale=1.15)

        def synthesize_wav(self, text, wav_file, *, syn_config):
            calls.append((text, syn_config.length_scale))
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\0\0" * 22050)

    backend = PiperTTSBackend(model_path=str(tmp_path / "jarvis.onnx"))
    backend._voice = Voice()
    result = backend.synthesize(
        "All systems operational.", voice_id="zm_yunxi", speed=2
    )

    assert calls == [("All systems operational.", 1.15 / 2)]
    assert result.voice_id == "jarvis-high"
    assert result.duration_seconds == 1
    with wave.open(io.BytesIO(result.audio), "rb") as wav_file:
        assert wav_file.getframerate() == 22050
        assert wav_file.getnframes() == 22050


@pytest.mark.parametrize(
    "requested, expected",
    [
        ("jarvis-high", "zm_yunjian"),
        ("zf_xiaoxiao", "zf_xiaoxiao"),
    ],
)
def test_chinese_and_mixed_text_preserve_mandarin_voice(tmp_path, requested, expected):
    backend = PiperTTSBackend(model_path=str(tmp_path / "jarvis.onnx"))
    backend._chinese_backend = Mock()
    backend._chinese_backend.synthesize.return_value = TTSResult(
        audio=b"wav", voice_id=expected
    )
    backend._voice = Mock()

    result = backend.synthesize("JARVIS，检查系统。", voice_id=requested, speed=1.1)

    backend._chinese_backend.synthesize.assert_called_once_with(
        "JARVIS，检查系统。", voice_id=expected, speed=1.1, output_format="wav"
    )
    backend._voice.synthesize_wav.assert_not_called()
    assert result.voice_id == expected


@pytest.mark.parametrize("speed", [0, -1, float("inf"), float("nan")])
def test_invalid_speed_is_rejected_before_loading(tmp_path, speed):
    backend = PiperTTSBackend(model_path=str(tmp_path / "missing.onnx"))
    with pytest.raises(ValueError, match="speed"):
        backend.synthesize("Test", speed=speed)


def test_missing_voice_is_unhealthy(tmp_path):
    assert not PiperTTSBackend(model_path=str(tmp_path / "missing.onnx")).health()


@pytest.mark.skipif(os.name != "nt", reason="Windows eSpeak narrow file API")
def test_unicode_install_uses_ascii_relative_espeak_path(tmp_path, monkeypatch):
    root = tmp_path / "中文安装"
    data = root / "runtime/piper/espeak-ng-data"
    data.mkdir(parents=True)
    monkeypatch.chdir(root)
    load = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=SimpleNamespace(load=load)))
    monkeypatch.setitem(sys.modules, "piper.phonemize_espeak", SimpleNamespace(ESPEAK_DATA_DIR=data))
    backend = PiperTTSBackend(model_path=str(root / "voice.onnx"))
    backend._load_voice()
    path = load.call_args.kwargs["espeak_data_dir"]
    assert path.isascii() and (root / path).resolve() == data.resolve()
    assert load.call_args.kwargs["use_cuda"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows eSpeak narrow file API")
def test_unicode_espeak_path_outside_install_rejects_before_native_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    load = Mock()
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=SimpleNamespace(load=load)))
    monkeypatch.setitem(sys.modules, "piper.phonemize_espeak", SimpleNamespace(ESPEAK_DATA_DIR=tmp_path / "中文安装/espeak-ng-data"))
    with pytest.raises(RuntimeError, match="安装目录"):
        PiperTTSBackend(model_path=str(tmp_path / "voice.onnx"))._load_voice()
    load.assert_not_called()
