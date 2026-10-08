import pytest
import tomlkit
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig
from openjarvis.server.deployment_routes import router


@pytest.fixture
def local_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.state.config = JarvisConfig()
    app.include_router(router)
    (tmp_path / "config.toml").write_text(
        '[agent]\ndefault_system_prompt = "owner persona"\n'
        '[memory]\nenabled = true\n[speech]\nvoice_id = "jarvis-high"\n',
        encoding="utf-8",
    )
    return app, tmp_path


def test_local_api_settings_preserve_identity_and_hide_key(local_settings):
    app, path = local_settings
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        response = client.post(
            "/v1/deployment/settings",
            json={
                "profile": "api",
                "model": "provider-model",
                "base_url": "https://provider.example/v1",
                "api_key": "test-secret",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["restart_required"] is True
        assert "test-secret" not in response.text
        saved = (path / "config.toml").read_text()
        assert "test-secret" not in saved
        doc = tomlkit.parse(saved)
        assert doc["agent"]["default_system_prompt"] == "owner persona"
        assert doc["memory"]["enabled"] is True
        assert doc["speech"]["voice_id"] == "jarvis-high"
        assert list(path.glob("config.before-model-*.toml"))
        result = client.get("/v1/deployment/settings")
        assert result.status_code == 200
        assert result.json()["has_api_key"]
        assert "test-secret" not in result.text


@pytest.mark.parametrize(
    "address,headers",
    [
        ("192.168.1.3", {}),
        ("127.0.0.1", {"Origin": "https://attacker.example"}),
        ("127.0.0.1", {"Origin": "http://127.0.0.1:9999"}),
        ("127.0.0.1", {"X-Forwarded-For": "10.0.0.4"}),
    ],
)
def test_settings_reject_remote_and_cross_origin(local_settings, address, headers):
    app, path = local_settings
    original = (path / "config.toml").read_bytes()
    with TestClient(app, client=(address, 4000)) as client:
        assert client.get("/v1/deployment/settings", headers=headers).status_code == 403
        result = client.post(
            "/v1/deployment/settings", headers=headers, json={"profile": "lite"}
        )
        assert result.status_code == 403
    assert (path / "config.toml").read_bytes() == original


def test_settings_honor_explicit_config_path(local_settings, monkeypatch):
    app, path = local_settings
    alternate = path / "alternate.toml"
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(alternate))
    original = (path / "config.toml").read_bytes()
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        assert (
            client.post("/v1/deployment/settings", json={"profile": "lite"}).status_code
            == 200
        )
    assert (path / "config.toml").read_bytes() == original
    assert tomlkit.parse(alternate.read_text())["engine"]["ollama"]["num_gpu"] == 0


def test_changed_endpoint_requires_restart(local_settings):
    app, path = local_settings
    app.state.config.engine.default = "api"
    app.state.config.engine.api.host = "https://old.example/v1"
    app.state.config.intelligence.default_model = "same-model"
    (path / "config.toml").write_text(
        '[engine]\ndefault = "api"\n'
        '[engine.api]\nhost = "https://new.example/v1"\n'
        '[intelligence]\ndefault_model = "same-model"\n',
        encoding="utf-8",
    )
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        assert client.get("/v1/deployment/settings").json()["restart_required"]


def test_owned_dynamic_ollama_port_is_not_reported_as_pending_restart(
    local_settings, monkeypatch
):
    app, path = local_settings
    runtime_url = "http://127.0.0.1:43123"
    app.state.config.engine.default = "ollama"
    app.state.config.engine.ollama.host = runtime_url
    app.state.config.intelligence.default_model = "qwen3.5:9b"
    monkeypatch.setenv("JARVIS_LOCAL_OLLAMA_URL", runtime_url)
    (path / "config.toml").write_text(
        '[engine]\ndefault = "ollama"\n'
        '[engine.ollama]\nhost = "http://127.0.0.1:11434"\n'
        '[intelligence]\ndefault_model = "qwen3.5:9b"\n',
        encoding="utf-8",
    )

    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        result = client.get("/v1/deployment/settings").json()

    assert result["restart_required"] is False
    assert result["base_url"] == "http://127.0.0.1:11434"
    assert result["local_base_url"] == runtime_url
