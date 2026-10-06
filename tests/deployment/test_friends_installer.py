"""Recipient installer validation, repair and key handling regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

SOURCE = Path(__file__).parents[2] / "deploy/share/configure_portable.py"
spec = importlib.util.spec_from_file_location("portable_installer", SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def request(**changes):
    return {
        "profile": "api",
        "model": "example-model",
        "url": "https://example.org/v1",
        "voice": "text",
        "key": "test-secret",
        **changes,
    }


@pytest.mark.parametrize(
    "address",
    [
        "",
        "example.org",
        "file:///C:/data",
        "https://key@example.org",
        "https://example.org?key=secret",
        "https://example.org:bad",
    ],
)
def test_invalid_api_address_rejected_before_writing(address):
    with pytest.raises(ValueError):
        installer.validate_request(request(url=address))


@pytest.mark.parametrize(
    "model", ["", "--help", "qwen\nsecret", "qwen name", "x" * 257]
)
def test_invalid_local_model_rejected(model):
    with pytest.raises(ValueError):
        installer.validate_request(request(profile="lite", model=model))


def test_reconfigure_backs_up_and_keyless_api_clears_stale_key(tmp_path):
    installer.run_action(tmp_path, "write", request())
    original = (tmp_path / "config.toml").read_bytes()
    installer.run_action(tmp_path, "write", request(key="", model="new-model"))
    backup = next(tmp_path.glob("config.before-setup-*.toml"))
    assert backup.read_bytes() == original
    assert "test-secret" not in (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "test-secret" not in (tmp_path / "credentials.toml").read_text(
        encoding="utf-8"
    )


def test_repair_preserves_all_existing_configuration_and_credentials(tmp_path):
    installer.run_action(tmp_path, "write", request())
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("config.toml", "credentials.toml")
    }
    read = installer.existing_request(tmp_path)
    assert read["preserve"] and read["model"] == "example-model"
    installer.run_action(tmp_path, "write", read)
    assert before == {name: (tmp_path / name).read_bytes() for name in before}
    assert not list(tmp_path.glob("config.before-setup-*.toml"))


def test_invalid_request_leaves_old_config_untouched(tmp_path):
    installer.run_action(tmp_path, "write", request())
    original = (tmp_path / "config.toml").read_bytes()
    with pytest.raises(ValueError):
        installer.run_action(tmp_path, "write", request(url="file:///bad"))
    assert (tmp_path / "config.toml").read_bytes() == original


def test_api_failure_does_not_echo_key_response_body_or_url(monkeypatch, tmp_path):
    response = httpx.Response(401, json={"error": "test-secret"})
    post = Mock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(ValueError) as exc:
        installer.check_request(tmp_path, request())
    assert "401" in str(exc.value) and "test-secret" not in str(exc.value)
    assert post.call_args.args[0] == "https://example.org/v1/chat/completions"


def test_failed_check_never_creates_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        httpx, "post", Mock(side_effect=httpx.ConnectError("test-secret"))
    )
    with pytest.raises(ValueError):
        installer.run_action(tmp_path, "check", request())
    assert not (tmp_path / "config.toml").exists()


def test_successful_api_check_exercises_chat_endpoint(monkeypatch, tmp_path):
    post = Mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "Hi"}}]}
        )
    )
    monkeypatch.setattr(httpx, "post", post)
    installer.check_request(tmp_path, request())
    assert post.call_args.kwargs["json"]["max_tokens"] == 1
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-secret"
