import json
from unittest.mock import MagicMock

import httpx
import pytest
import tomlkit
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.server.app import create_app
from openjarvis.server.deployment_routes import router
from openjarvis.server.routes import _uses_direct_cloud_router


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("THIRD_PARTY_API_KEY", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(
        '[engine]\ndefault="ollama"\n[intelligence]\ndefault_model="local"\n'
    )
    app = FastAPI()
    app.include_router(router)
    return app, path


def test_supplement_preserves_primary_and_secret_and_roundtrips(setup):
    app, path = setup
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        result = client.post(
            "/v1/deployment/third-party-api",
            json={
                "base_url": "https://api.test",
                "name": "中科大",
                "enabled": True,
                "models": ["qwen-chat", "glm-id"],
                "api_key": "sample-key",
            },
        )
        assert result.status_code == 200, result.text
        saved = tomlkit.parse(path.read_text(encoding="utf-8"))
        assert saved["engine"]["default"] == "ollama"
        assert saved["intelligence"]["default_model"] == "local"
        assert saved["engine"]["third_party_api"]["name"] == "中科大"
        assert "sample-key" not in path.read_text(encoding="utf-8")
        assert list(path.parent.glob("config.before-third-party-api-*.toml"))
        settings = client.get("/v1/deployment/third-party-api")
        assert settings.json()["has_api_key"]
        assert settings.json()["name"] == "中科大"
        assert "sample-key" not in settings.text
        assert load_config(path).engine.third_party_api.models == [
            "qwen-chat",
            "glm-id",
        ]
        assert (
            client.post(
                "/v1/deployment/third-party-api",
                json={
                    "base_url": "https://api.test",
                    "models": ["qwen-chat"],
                    "enabled": False,
                    "clear_api_key": True,
                },
            ).status_code
            == 200
        )
        assert not client.get("/v1/deployment/third-party-api").json()["has_api_key"]


@pytest.mark.parametrize("endpoint", ["/third-party-api", "/third-party-api/test"])
def test_remote_configuration_is_rejected(setup, endpoint):
    app, _ = setup
    with TestClient(app, client=("192.168.1.2", 4000)) as client:
        assert client.post("/v1/deployment" + endpoint, json={}).status_code == 403


def test_rename_keeps_models_and_key_but_new_endpoint_requires_its_key(setup):
    app, _ = setup
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        body = {
            "enabled": True,
            "name": "中科大",
            "models": ["qwen-chat"],
            "base_url": "https://api.test/gateway/v1",
            "api_key": "sample-key",
        }
        assert (
            client.post("/v1/deployment/third-party-api", json=body).status_code == 200
        )
        body.pop("api_key")
        body["name"] = "实验室"
        assert (
            client.post("/v1/deployment/third-party-api", json=body).status_code == 200
        )
        data = client.get("/v1/deployment/third-party-api").json()
        assert data["name"] == "实验室"
        assert data["models"] == ["qwen-chat"] and data["has_api_key"]
        body["base_url"] = "https://different.test/v1"
        assert (
            client.post("/v1/deployment/third-party-api/test", json=body).status_code
            == 422
        )
        assert (
            client.post("/v1/deployment/third-party-api", json=body).status_code == 422
        )


def test_old_development_settings_migrate_with_the_saved_key(setup):
    from openjarvis.core.credentials import save_credential

    app, path = setup
    path.write_text(
        '[engine]\ndefault="ollama"\n[engine.ustc]\nenabled=true\n'
        'host="https://api.llm.ustc.edu.cn"\nmodels=["qwen-chat"]\n',
        encoding="utf-8",
    )
    save_credential("ustc", "USTC_API_KEY", "legacy-key")
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        data = client.get("/v1/deployment/third-party-api").json()
        assert data["name"] == "中科大" and data["has_api_key"]
        data.pop("has_api_key")
        assert (
            client.post("/v1/deployment/third-party-api", json=data).status_code == 200
        )
        saved = tomlkit.parse(path.read_text(encoding="utf-8"))
        assert not saved["engine"]["ustc"]["enabled"]
        assert saved["engine"]["third_party_api"]["name"] == "中科大"
        assert client.get("/v1/deployment/third-party-api").json()["has_api_key"]


def test_probe_without_persisting_and_models_optional(setup, monkeypatch):
    app, path = setup
    original = path.read_bytes()

    def handler(request):
        assert request.headers["Authorization"] == "Bearer sample-key"
        if request.method == "GET":
            return httpx.Response(404)
        assert json.loads(request.content)["model"] == "qwen-chat"
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original_client(
            **kw,
            transport=httpx.MockTransport(handler),
        ),
    )
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        result = client.post(
            "/v1/deployment/third-party-api/test",
            json={
                "api_key": "sample-key",
                "base_url": "https://api.test",
                "models": ["qwen-chat"],
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["reply"] == "你好"
        assert result.json()["available_models"] == []
    assert path.read_bytes() == original
    assert not (path.parent / "credentials.toml").exists()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_probe_reports_failure_without_upstream_secret(setup, monkeypatch, status):
    app, _ = setup
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original_client(
            **kw,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, text="sample-key")
            ),
        ),
    )
    with TestClient(app, client=("127.0.0.1", 4000)) as client:
        result = client.post(
            "/v1/deployment/third-party-api/test",
            json={
                "api_key": "sample-key",
                "base_url": "https://api.test",
                "models": ["qwen-chat"],
            },
        )
        assert result.status_code == 502
        assert str(status) in result.text
        assert "sample-key" not in result.text


def test_selected_gateway_stream_uses_third_party_api_while_local_stays_local(
    setup, monkeypatch
):
    monkeypatch.setenv("THIRD_PARTY_API_KEY", "sample-key")
    cfg = JarvisConfig()
    cfg.engine.third_party_api.enabled = True
    cfg.engine.third_party_api.host = "https://api.test"
    cfg.engine.third_party_api.name = "中科大"
    cfg.engine.third_party_api.models = ["qwen-chat", "vendor/model"]
    cfg.security.enabled = cfg.analytics.enabled = cfg.traces.enabled = False
    local = MagicMock()
    local.engine_id = "ollama"
    local.list_models.return_value = ["local"]
    local.generate.return_value = {"content": "local reply", "usage": {}}
    app = create_app(local, "local", config=cfg)
    gateway = app.state.engine._engine_for("third-party/qwen-chat")

    def handler(request):
        assert json.loads(request.content)["model"] == "qwen-chat"
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"gateway reply"}}]}\n\n'
            "data: [DONE]\n\n",
        )

    gateway._async_transport = httpx.MockTransport(handler)
    with TestClient(app) as client:
        models = client.get("/v1/models").json()["data"]
        assert {row["id"] for row in models} == {
            "local",
            "third-party/qwen-chat",
            "third-party/vendor/model",
        }
        assert (
            next(row for row in models if row["id"] == "third-party/qwen-chat")[
                "display_name"
            ]
            == "中科大 / qwen-chat"
        )
        assert not _uses_direct_cloud_router(
            app.state.engine, "third-party/vendor/model"
        )
        result = client.post(
            "/v1/chat/completions",
            json={
                "model": "third-party/qwen-chat",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert "gateway reply" in result.text, result.text
        assert not local.generate.called
        assert (
            client.post(
                "/v1/chat/completions",
                json={
                    "model": "local",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            ).status_code
            == 200
        )
        assert local.generate.called
        assert (
            client.post(
                "/v1/chat/completions",
                json={
                    "model": "third-party/not-configured",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            ).status_code
            == 400
        )
    app.state.engine.close()
