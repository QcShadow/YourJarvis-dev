from pathlib import Path

import pytest
import tomlkit
from click.testing import CliRunner

from openjarvis.cli.setup_cmd import configure
from openjarvis.core.deployment import configuration_text, write_configuration


def test_lite_config_is_portable_and_limits_resources(tmp_path):
    data = tomlkit.parse(configuration_text(tmp_path))
    assert data["engine"]["ollama"]["num_gpu"] == 0
    assert data["engine"]["ollama"]["num_ctx"] == 2048
    assert data["intelligence"]["default_model"] == "qwen2.5:0.5b"
    assert data["agent"]["default_agent"] == "simple"
    assert data["memory"]["enabled"] is False
    assert "D:/Jarvis" not in str(data)
    assert data["speech"]["chinese_model"] == str(tmp_path / "models/speech/sensevoice")
    assert "facts_path" not in data["memory"]


def test_configuration_refuses_overwrite_and_preserves_backup(tmp_path):
    path = tmp_path / "config.toml"
    original = '[agent]\ndefault_system_prompt = "private persona"\n'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_configuration(tmp_path)
    assert path.read_text(encoding="utf-8") == original
    write_configuration(tmp_path, replace=True)
    assert (
        next(tmp_path.glob("config.before-setup-*.toml")).read_text(encoding="utf-8")
        == original
    )


def test_full_client_retains_features_with_lite_model(tmp_path):
    data = tomlkit.parse(configuration_text(tmp_path, full_features=True))
    assert data["intelligence"]["default_model"] == "qwen2.5:0.5b"
    assert data["engine"]["ollama"]["num_gpu"] == 0
    assert data["agent"]["default_agent"] == "orchestrator"
    assert data["agent"]["context_from_memory"] is True
    assert data["memory"]["enabled"] is True
    assert {"shell_exec", "file_read", "web_search"} <= set(data["tools"]["enabled"])
    assert data["deployment"]["full_features"] is True


def test_api_wizard_separates_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    result = CliRunner().invoke(
        configure,
        [
            "--profile",
            "api",
            "--model",
            "custom-chinese-model",
            "--base-url",
            "https://provider.example/compatible-mode/v1",
            "--prompt-api-key",
            "--voice",
            "text",
        ],
        input="test-api-secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "test-api-secret" not in result.output
    assert "test-api-secret" not in (tmp_path / "config.toml").read_text(
        encoding="utf-8"
    )
    assert "test-api-secret" in (tmp_path / "credentials.toml").read_text(
        encoding="utf-8"
    )
    assert 'host = "https://provider.example/compatible-mode"' in (
        tmp_path / "config.toml"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "https://key:secret@example.org",
        "https://example.org?api_key=secret",
        "http://a:bad",
    ],
)
def test_reject_bad_api_endpoints(tmp_path, url):
    with pytest.raises(ValueError):
        configuration_text(tmp_path, profile="api", model="qwen", base_url=url)


def test_config_loads_resource_settings(monkeypatch, tmp_path):
    from openjarvis.core.config import load_config

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    write_configuration(tmp_path)
    cfg = load_config()
    assert cfg.engine.ollama.num_ctx == 2048
    assert cfg.engine.ollama.num_gpu == 0


def test_package_excludes_owner_state_and_large_models(tmp_path):
    import importlib.util

    source = Path(__file__).parents[2] / "deploy/share/build_package.py"
    spec = importlib.util.spec_from_file_location("build_share_package", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE"):
        path = tmp_path / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    code = tmp_path / "src/src/openjarvis"
    code.mkdir(parents=True)
    (code / "__init__.py").write_text("# fixture")
    (code / ".env").write_text("source-secret")
    for name in module.RUNTIME_FILES:
        path = tmp_path / "src/deploy/share/runtime" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    for name in (
        "install-jarvis.ps1",
        "install-jarvis.cmd",
        "install-worker.ps1",
        "configure_portable.py",
        "bootstrap.ps1",
        "bootstrap.cmd",
        "download-speech.ps1",
        "download-speech.cmd",
        "download_speech_assets.py",
        "smoke_installed.py",
        "verify_voice.py",
        "README.zh-CN.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        (tmp_path / "src/deploy/share" / name).write_text("fixture")
    (tmp_path / "tools/uv").mkdir(parents=True)
    (tmp_path / "tools/uv/uv.exe").write_bytes(b"fixture")
    for name in (
        "config.toml",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        "credentials.toml",
        "friends-members.json",
        "memory.db",
        "memory_facts.jsonl",
    ):
        (tmp_path / name).write_text("OWNER-SECRET")
    (tmp_path / "models/ollama/blobs").mkdir(parents=True)
    (tmp_path / "models/ollama/blobs/huge-model").write_text("OWNER-MODEL")
    output = tmp_path / "share.zip"
    manifest = module.build_package(tmp_path, output)
    paths = {f["path"] for f in manifest["files"]}
    assert "config.toml" not in paths
    assert "src/src/openjarvis/.env" not in paths
    assert not any(p.startswith("models/") for p in paths)
    import zipfile

    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(b"OWNER-SECRET" in archive.read(n) for n in archive.namelist())
    with pytest.raises(FileExistsError):
        module.build_package(tmp_path, output)
