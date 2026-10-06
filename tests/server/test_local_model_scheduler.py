"""Resource leases must restore voice on failure and serialize image jobs."""

import threading
import urllib.error
import json

import pytest

from openjarvis.core import model_scheduler as scheduler


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(scheduler, "_TASKS", [])
    calls = []

    def request(url, payload=None, timeout=3):
        calls.append(url)
        if url.endswith("/health"):
            return {"identity": "jarvis-high-qwen-local-v1"}
        return {"loaded": False}

    monkeypatch.setattr(scheduler, "local_request", request)
    monkeypatch.setattr(scheduler, "gpu_memory", lambda: {"free_mib": 6000})
    return tmp_path, calls


def test_gpu_failure_releases_image_before_resuming_voice(state):
    root, calls = state
    with pytest.raises(RuntimeError, match="generation failed"):
        with scheduler.image_job("a forest") as allocation:
            assert allocation["device"] == "cuda"
            assert (root / "data/gpu-image-lease.json").is_file()
            raise RuntimeError("generation failed")
    assert calls.index("http://127.0.0.1:3338/unload") < calls.index("http://127.0.0.1:3337/resume")
    assert not (root / "data/gpu-image-lease.json").exists()
    assert scheduler.tasks()[0]["status"] == "failed"


def test_corrupt_scheduler_state_falls_back_to_safe_defaults(state):
    root, _ = state
    path = root / "data/model-scheduler.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[not an object]", encoding="utf-8")

    assert scheduler.settings() == scheduler.DEFAULTS


def test_partially_invalid_scheduler_state_is_normalized(state):
    root, _ = state
    path = root / "data/model-scheduler.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"image_device":"cuda","main_during_image":"bad",'
        '"voice_wait_seconds":true,"writer_idle_seconds":30,'
        '"ignored":"private"}',
        encoding="utf-8",
    )

    result = scheduler.settings()
    assert result["image_device"] == "cuda"
    assert result["main_during_image"] == "cpu"
    assert result["voice_wait_seconds"] == scheduler.DEFAULTS["voice_wait_seconds"]
    assert result["writer_idle_seconds"] == 30
    assert "ignored" not in result


def test_auto_falls_back_to_cpu_without_holding_voice(state, monkeypatch):
    root, calls = state
    monkeypatch.setattr(scheduler, "gpu_memory", lambda: {"free_mib": 900})
    with scheduler.image_job("a lake") as allocation:
        assert allocation["device"] == "cpu"
        assert calls[-1].endswith("/resume")
        assert not (root / "data/gpu-image-lease.json").exists()
    assert not any(url.endswith("/unload") for url in calls)


def test_explicit_gpu_does_not_evict_main_when_vram_is_low(state, monkeypatch):
    root, calls = state
    scheduler.save_settings({"image_device": "cuda"})
    monkeypatch.setattr(scheduler, "gpu_memory", lambda: {"free_mib": 900})
    with pytest.raises(RuntimeError, match="主助手保持运行"):
        with scheduler.image_job("a castle"):
            pytest.fail("A GPU job cannot start without available VRAM")
    assert calls[-1].endswith("/resume")
    assert not (root / "data/gpu-image-lease.json").exists()
    assert not any("11434" in url for url in calls)


def test_cpu_policy_never_suspends_voice(state):
    _, calls = state
    scheduler.save_settings({"image_device": "cpu"})
    with scheduler.image_job("a portrait") as allocation:
        assert allocation["device"] == "cpu"
    assert calls == []


def test_busy_voice_timeout_uses_cpu_in_auto(state, monkeypatch):
    root, calls = state
    scheduler.save_settings({"voice_wait_seconds": 0})

    def busy(url, payload=None, timeout=3):
        calls.append(url)
        if url.endswith("/suspend"):
            raise urllib.error.HTTPError(url, 409, "busy", {}, None)
        return {"identity": "jarvis-high-qwen-local-v1"}

    monkeypatch.setattr(scheduler, "local_request", busy)
    with scheduler.image_job("a mountain") as allocation:
        assert allocation["device"] == "cpu"
        assert not (root / "data/gpu-image-lease.json").exists()


def test_queued_job_cannot_remove_active_lease(state):
    root, _ = state
    first_entered = threading.Event()
    second_queued = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    errors = []

    def first():
        try:
            with scheduler.image_job("first"):
                first_entered.set()
                assert release_first.wait(3)
        except Exception as exc:
            errors.append(exc)

    def second():
        try:
            second_queued.set()
            with scheduler.image_job("second"):
                assert (root / "data/gpu-image-lease.json").is_file()
                second_entered.set()
        except Exception as exc:
            errors.append(exc)

    a = threading.Thread(target=first)
    b = threading.Thread(target=second)
    a.start()
    assert first_entered.wait(2)
    b.start()
    assert second_queued.wait(2)
    assert not second_entered.is_set()
    assert (root / "data/gpu-image-lease.json").is_file()
    release_first.set()
    a.join(3)
    b.join(3)
    assert not a.is_alive() and not b.is_alive()
    assert not errors
    assert second_entered.is_set()


def test_main_migrates_to_cpu_and_restores_after_image_unload(state, monkeypatch):
    root, calls = state
    monkeypatch.setattr(scheduler, "main_model", lambda: "qwen3.5:9b")
    monkeypatch.setattr(scheduler, "available_ram_mib", lambda: 10000)
    migrations = []
    monkeypatch.setattr(scheduler, "preload_main", lambda model, device, ctx: migrations.append((device, list(calls))))
    with scheduler.image_job("cover"):
        lease = json.loads((root / "data/gpu-image-lease.json").read_text())
        assert lease["main_device"] == "cpu"
        assert not scheduler.WRITER_LOCK.acquire(blocking=False)
    assert [device for device, _ in migrations] == ["cpu", "gpu"]
    assert any(url.endswith("3338/unload") for url in migrations[1][1])
    assert scheduler.WRITER_LOCK.acquire(blocking=False)
    scheduler.WRITER_LOCK.release()


def test_main_cpu_lease_overrides_chat_options_only_for_main(state, monkeypatch):
    from openjarvis.engine.ollama import _ollama_request_options

    monkeypatch.setattr(scheduler, "main_model", lambda: "qwen3.5:9b")
    monkeypatch.setattr(scheduler, "available_ram_mib", lambda: 10000)
    monkeypatch.setattr(scheduler, "preload_main", lambda *args: None)
    with scheduler.image_job("cover"):
        main = _ollama_request_options(model="qwen3.5:9b", temperature=.3, max_tokens=100,
                                       kwargs={"num_gpu": -1, "num_ctx": 4096})
        writer = _ollama_request_options(model="jarvis-writer:4b", temperature=.3, max_tokens=100,
                                         kwargs={"num_gpu": 0, "num_ctx": 8192})
        assert main["num_gpu"] == 0 and main["num_ctx"] == 16384
        assert writer["num_gpu"] == 0 and writer["num_ctx"] == 8192


def test_insufficient_ram_does_not_move_main_in_auto_mode(state, monkeypatch):
    monkeypatch.setattr(scheduler, "main_model", lambda: "qwen3.5:9b")
    monkeypatch.setattr(scheduler, "available_ram_mib", lambda: 2000)
    monkeypatch.setattr(scheduler, "preload_main", lambda *args: pytest.fail("Must not exhaust RAM"))
    with scheduler.image_job("cover") as allocation:
        assert allocation["device"] == "cuda"
        assert not scheduler.image_lease().get("main_model")


def test_failed_image_unload_keeps_cpu_lease_and_voice_paused(state, monkeypatch):
    root, calls = state
    original = scheduler.local_request
    def request(url, payload=None, timeout=3):
        if url.endswith("3338/unload"):
            raise TimeoutError("worker busy")
        return original(url, payload, timeout)
    monkeypatch.setattr(scheduler, "local_request", request)
    with pytest.raises(TimeoutError):
        with scheduler.image_job("cover"):
            pass
    assert (root / "data/gpu-image-lease.json").exists()
    assert not any(url.endswith("/resume") for url in calls)


def test_failed_main_migration_restores_gpu_and_preserves_failure(state, monkeypatch):
    root, _ = state
    monkeypatch.setattr(scheduler, "main_model", lambda: "qwen3.5:9b")
    monkeypatch.setattr(scheduler, "available_ram_mib", lambda: 10000)
    migrations = []
    def preload(model, device, ctx):
        migrations.append(device)
        if device == "cpu":
            raise RuntimeError("load failed")
    monkeypatch.setattr(scheduler, "preload_main", preload)
    with pytest.raises(RuntimeError, match="load failed"):
        with scheduler.image_job("cover"):
            pytest.fail("Generation cannot start after a failed migration")
    assert migrations == ["cpu", "gpu"]
    assert scheduler.tasks()[0]["status"] == "failed"
    assert not (root / "data/gpu-image-lease.json").exists()
    assert scheduler.WRITER_LOCK.acquire(blocking=False)
    scheduler.WRITER_LOCK.release()
