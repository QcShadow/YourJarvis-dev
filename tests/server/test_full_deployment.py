from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig
from openjarvis.core.deployment import write_configuration
from openjarvis.server.deployment_routes import router


def test_full_model_switch_preserves_complete_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_PORTABLE_CLIENT", "1")
    write_configuration(tmp_path, full_features=True)
    app = FastAPI()
    app.state.config = JarvisConfig()
    app.include_router(router)
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        defaults = client.get("/v1/deployment/bootstrap").json()["settings"]
        assert defaults["defaultAgent"] == "orchestrator"
        assert defaults["wakeWordEnabled"] is True
        response = client.post(
            "/v1/deployment/settings",
            json={
                "profile": "remote-host",
                "base_url": "http://host.test:8001/v1",
                "api_key": "jf_sample",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["model"] == "host-model"
        import tomlkit

        config = tomlkit.parse((tmp_path / "config.toml").read_text(encoding="utf-8"))
        assert config["agent"]["default_agent"] == "orchestrator"
        assert config["memory"]["enabled"] is True
        assert "file_read" in config["tools"]["enabled"]
        assert config["deployment"]["full_features"] is True
        assert "jf_sample" not in str(config)
