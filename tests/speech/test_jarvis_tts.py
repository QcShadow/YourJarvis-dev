"""Verify language routing and persistence of the selected voice identity."""

import io
import json
import wave
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.speech.jarvis_tts import JarvisTTSBackend


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b"\x00\x00" * 2400)
    return output.getvalue()


def test_saved_kokoro_voice_does_not_replace_chinese_jarvis():
    backend = JarvisTTSBackend()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = wav()
    with (
        patch.object(backend, "_ensure_worker"),
        patch("urllib.request.urlopen", return_value=response) as send,
    ):
        result = backend.synthesize(
            "你好，我是贾维斯。", voice_id="zm_yunjian", speed=1.1
        )
    request = send.call_args.args[0]
    assert json.loads(request.data) == {"text": "你好，我是贾维斯。", "speed": 1.1}
    assert result.voice_id == "jarvis-high"
    assert result.sample_rate == 24000
    assert result.duration_seconds == 0.1
    assert backend.english._chinese_backend is None


def test_english_uses_original_piper_without_starting_gpu_worker():
    backend = JarvisTTSBackend()
    with (
        patch.object(backend.english, "synthesize") as synthesize,
        patch.object(backend, "_ensure_worker") as worker,
    ):
        backend.synthesize("All systems operational.", voice_id="zf_xiaoxiao")
    synthesize.assert_called_once_with(
        "All systems operational.", voice_id="jarvis-high", speed=1.0
    )
    worker.assert_not_called()


def test_unrelated_service_is_not_accepted_as_voice_worker():
    backend = JarvisTTSBackend()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        b'{"identity": "other-service", "ready": true}'
    )
    with (
        patch("urllib.request.urlopen", return_value=response),
        pytest.raises(RuntimeError, match="occupied"),
    ):
        backend._ready()


@pytest.mark.parametrize("speed", [0, float("nan"), float("inf"), 3])
def test_invalid_speed(speed):
    with pytest.raises(ValueError, match="speed"):
        JarvisTTSBackend().synthesize("你好", speed=speed)
