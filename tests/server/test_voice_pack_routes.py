"""Import/management and both speech transports use the same user profile."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from openjarvis.server.api_routes import speech_router
from openjarvis.server.voice_pack_routes import router
from openjarvis.speech.preferences import save_preference
from openjarvis.speech.tts import TTSResult
from tests.speech.test_voice_packs import recording


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENJARVIS_VOICE_STATE_PATH", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.include_router(speech_router)
    return TestClient(app)


def upload(client):
    response = client.post(
        "/v1/speech/packs/import",
        data={"name": "我的声音", "transcript": "你好。"},
        files=[("files", ("voice.wav", recording(), "audio/wav"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_management_roundtrip(client):
    value = upload(client)
    assert "_pack_root" not in value
    assert client.get("/v1/speech/packs").json()["packs"][0]["id"] == value["id"]
    assert any(
        v["id"] == value["id"]
        for v in client.get("/v1/speech/profiles").json()["voices"]
    )
    assert (
        client.patch(f"/v1/speech/packs/{value['id']}", json={"name": "改名"}).json()[
            "name"
        ]
        == "改名"
    )
    exported = client.get(f"/v1/speech/packs/{value['id']}/export")
    imported = client.post(
        "/v1/speech/packs/import", files=[("files", ("voice.jvoice", exported.content))]
    )
    assert imported.status_code == 201 and imported.json()["id"] != value["id"]
    assert client.delete(f"/v1/speech/packs/{value['id']}").status_code == 204


def test_remote_origin_cannot_manage_library(client):
    response = client.post(
        "/v1/speech/packs/import",
        headers={"Origin": "https://evil.example"},
        data={"name": "voice", "transcript": "hello"},
        files=[("files", ("voice.wav", recording()))],
    )
    assert response.status_code == 403
    assert client.get("/v1/speech/packs").json()["packs"] == []


def test_bad_files_and_saved_background_selection(client):
    invalid = client.post(
        "/v1/speech/packs/import",
        data={"name": "voice", "transcript": "hello"},
        files=[("files", ("voice.wav", b"not audio"))],
    )
    assert invalid.status_code == 422
    value = upload(client)
    save_preference(enabled=True, options={"voice_profile": value["id"]})
    assert client.delete(f"/v1/speech/packs/{value['id']}").status_code == 409
    save_preference(enabled=False)
    assert client.delete(f"/v1/speech/packs/{value['id']}").status_code == 204


def test_custom_voice_stream_and_wav_keep_language(client):
    value = upload(client)
    backend = Mock()
    backend._voice_profile_lock = threading.Lock()
    backend.supports_streaming.return_value = True
    backend.synthesize_stream.return_value = iter([(b"\0\0" * 8, 24000)])
    backend.synthesize.return_value = TTSResult(
        audio=recording(), voice_id=value["id"], sample_rate=24000
    )
    body = {"text": "I'm here.", "voice_profile": value["id"], "output_language": "en"}
    with patch(
        "openjarvis.speech.profiles.profile_backend",
        new=AsyncMock(return_value=backend),
    ):
        result = client.post("/v1/speech/stream", json=body)
        assert result.status_code == 200 and result.headers["X-Voice-Id"] == value["id"]
        assert backend.synthesize_stream.call_args.kwargs["language"] == "en"
        result = client.post("/v1/speech/synthesize", json=body)
        assert result.status_code == 200 and result.headers["X-Voice-Id"] == value["id"]
        assert backend.synthesize.call_args.kwargs["language"] == "en"


@pytest.mark.anyio
async def test_native_voice_binds_language_to_each_callback(client):
    from openjarvis.server.voice_routes import StartVoiceRequest, _start_voice

    value = upload(client)
    backend = Mock()
    backend._voice_profile_lock = threading.Lock()
    backend.supports_streaming.return_value = True
    backend.synthesize.return_value = TTSResult(audio=recording(), voice_id=value["id"])
    runtime = SimpleNamespace(
        running=False, start=AsyncMock(), snapshot=lambda: {}, delegate=Mock()
    )
    client.app.state.voice_runtime = runtime
    request = Request({"type": "http", "app": client.app, "headers": []})
    with patch(
        "openjarvis.speech.profiles.profile_backend",
        new=AsyncMock(return_value=backend),
    ):
        await _start_voice(
            StartVoiceRequest(voice_profile=value["id"], output_language="en"), request
        )
        previous = runtime.synthesize
        await _start_voice(
            StartVoiceRequest(voice_profile=value["id"], output_language="zh"), request
        )
        previous("Hello.", voice_profile=value["id"])
        assert backend.synthesize.call_args.kwargs["language"] == "en"
        runtime.synthesize("你好。", voice_profile=value["id"])
        assert backend.synthesize.call_args.kwargs["language"] == "zh"
