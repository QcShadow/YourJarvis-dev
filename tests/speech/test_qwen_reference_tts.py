"""Reference transport and worker prompt caching without loading GPU weights."""

import base64
import importlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from openjarvis.speech.qwen_reference_tts import QwenReferenceTTSBackend
from tests.speech.test_voice_packs import recording, reference


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    return importlib.import_module("qwen_tts_server")


def test_worker_reference_identity_and_explicit_english(worker):
    pool = SimpleNamespace(
        engine="faster",
        device="cpu",
        voice=None,
        lock=threading.Lock(),
        suspended=threading.Event(),
        synthesize=Mock(return_value=recording()),
        stream=Mock(return_value=iter([b"\0\0" * 8])),
    )
    client = TestClient(worker.create_app(pool, "jarvis-high-qwen-local-v1:test"))
    voice_id = "user-" + "a" * 32
    body = {
        "text": "Jarvis is here.",
        "voice_id": voice_id,
        "language": "English",
        "reference_audio": base64.b64encode(recording()).decode(),
        "reference_text": "Hello.",
    }
    result = client.post("/synthesize", json=body)
    assert result.status_code == 200 and result.headers["X-Voice-Id"] == voice_id
    assert pool.synthesize.call_args.kwargs["language"] == "English"
    assert pool.synthesize.call_args.kwargs["reference"][1] == "Hello."
    assert client.post("/stream", json=body).headers["X-Voice-Id"] == voice_id
    health = client.get("/health").json()
    assert health["reference_api"] == 1
    assert health["identity"] == "jarvis-high-qwen-local-v1:test"
    body["voice_id"] = "jarvis-high"
    assert client.post("/synthesize", json=body).status_code == 422
    body["voice_id"] = voice_id
    body["reference_audio"] = "not base64"
    assert client.post("/synthesize", json=body).status_code == 422


def test_prompt_cache_key_includes_audio_and_transcript_and_is_bounded(worker):
    voice = object.__new__(worker.Voice)
    voice.prompt = object()
    voice.prompts = OrderedDict()
    voice.base = Mock()
    voice.base.create_voice_clone_prompt.side_effect = lambda **kwargs: object()
    audio = recording()
    first = voice._reference_prompt((audio, "one"))
    assert voice._reference_prompt((audio, "one")) is first
    assert voice._reference_prompt((audio, "two")) is not first
    for number in range(5):
        voice._reference_prompt((recording(number + 2), str(number)))
    assert len(voice.prompts) == 4
    assert voice._reference_prompt(None) is voice.prompt
    assert "Jarvis" in "".join(worker.Voice.chunks("Jarvis is here.", "English"))


def test_reference_transport_never_routes_english_to_piper(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    profile = reference()
    backend = QwenReferenceTTSBackend(profile)
    health = Mock()
    health.__enter__ = Mock(return_value=health)
    health.__exit__ = Mock(return_value=False)
    health.read.return_value = b'{"reference_api": 1}'
    audio = Mock()
    audio.__enter__ = Mock(return_value=audio)
    audio.__exit__ = Mock(return_value=False)
    audio.read.return_value = recording()
    audio.headers = {"X-Voice-Id": profile["id"]}
    with (
        patch.object(backend, "_ensure_worker"),
        patch("urllib.request.urlopen", side_effect=[health, audio]) as send,
    ):
        result = backend.synthesize("I'm here.", voice_id=profile["id"], language="en")
    payload = json.loads(send.call_args.args[0].data)
    assert payload["voice_id"] == profile["id"] and payload["language"] == "English"
    assert base64.b64decode(payload["reference_audio"]) == recording()
    assert result.voice_id == profile["id"]
    assert not hasattr(backend, "english")
