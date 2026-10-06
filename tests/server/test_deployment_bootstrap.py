from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.deployment import write_configuration
from openjarvis.server.deployment_routes import router


def test_fresh_browser_follows_text_lite_preset(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    write_configuration(tmp_path, voice="text")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, client=("127.0.0.1", 1000)) as client:
        result = client.get("/v1/deployment/bootstrap").json()
    settings = result["settings"]
    assert result["configured"]
    assert settings["defaultModel"] == "qwen2.5:0.5b"
    assert settings["maxTokens"] == 256
    assert not settings["automaticModelRouting"]
    assert not settings["voiceOutputEnabled"]
    assert not settings["wakeWordEnabled"]


def test_existing_owner_config_keeps_browser_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text('[engine]\ndefault = "ollama"\n')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, client=("127.0.0.1", 1000)) as client:
        assert client.get("/v1/deployment/bootstrap").json() == {"configured": False}
