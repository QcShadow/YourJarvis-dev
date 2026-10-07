import io
import wave
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.voice_pack_routes import router
from openjarvis.speech import voice_packs


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENJARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('OPENJARVIS_RESOURCE_ROOT', str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def wav():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
        output.writeframes(np.random.default_rng(1).integers(-1000,1000,size=24000,dtype=np.int16).astype('<i2').tobytes())
    return stream.getvalue()


def create(client):
    return client.post('/v1/speech/packs/import', files={'files': ('clean.wav', wav(), 'audio/wav')}, data={'name':'测试音色','embedding_only':'true','generate':'true'})


def test_missing_model_rejects_before_saving(client):
    assert create(client).status_code == 409
    assert voice_packs.catalog() == []


def test_creation_generates_audition_and_can_be_shared(client):
    with patch('openjarvis.speech.resources.installed', return_value={'clone': True}), patch('openjarvis.speech.profiles.profile_backend', new_callable=AsyncMock), patch('openjarvis.speech.profiles.synthesize_profile', return_value=SimpleNamespace(audio=wav())) as generate:
        response = create(client)
    assert response.status_code == 201
    pack_id = response.json()['id']
    assert generate.call_count == 1
    assert client.get(f'/v1/speech/packs/{pack_id}/preview').content == wav()
    assert client.get(f'/v1/speech/packs/{pack_id}/export').status_code == 200
    assert voice_packs.read_manifest(pack_id)['embedding_only']


def test_failed_generation_removes_new_voice(client):
    with patch('openjarvis.speech.resources.installed', return_value={'clone': True}), patch('openjarvis.speech.profiles.profile_backend', new_callable=AsyncMock), patch('openjarvis.speech.profiles.synthesize_profile', side_effect=RuntimeError('model error')):
        assert create(client).status_code == 503
    assert voice_packs.catalog() == []


def test_remote_origin_cannot_modify_library(client):
    assert client.post('/v1/speech/packs/import', headers={'Origin':'https://remote.example'}, files={'files':('a.wav',wav())}, data={'name':'voice','embedding_only':'true'}).status_code == 403
