"""Local workload policy, image GPU leases, and observable task history."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from openjarvis.core.paths import get_config_dir, get_resource_dir

_VOICE_URL = os.environ.get("JARVIS_VOICE_URL", "http://127.0.0.1:3337")
_IMAGE_URL = os.environ.get("JARVIS_IMAGE_URL", "http://127.0.0.1:3338")
_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not _OLLAMA_URL.startswith(("http://", "https://")):
    _OLLAMA_URL = "http://" + _OLLAMA_URL

DEFAULTS = {"image_device": "auto", "voice_idle_seconds": 120,
            "writer_idle_seconds": 120, "cpu_image_idle_seconds": 120,
            "voice_wait_seconds": 120, "main_during_image": "cpu"}
_INT_SETTINGS = ("voice_idle_seconds", "writer_idle_seconds",
                 "cpu_image_idle_seconds", "voice_wait_seconds")
_IMAGE_DEVICES = frozenset({"auto", "cpu", "cuda"})
_MAIN_POLICIES = frozenset({"cpu", "keep"})
_STATE_LOCK = threading.RLock()
_IMAGE_LOCK = threading.Lock()
WRITER_LOCK = threading.Lock()
_TASKS = []


def settings_path():
    return get_config_dir() / "data/model-scheduler.json"


def _validated_settings(saved):
    """Return safe defaults for malformed or partially edited local state."""
    if not isinstance(saved, dict):
        return dict(DEFAULTS)
    result = dict(DEFAULTS)
    if saved.get("image_device") in _IMAGE_DEVICES:
        result["image_device"] = saved["image_device"]
    if saved.get("main_during_image") in _MAIN_POLICIES:
        result["main_during_image"] = saved["main_during_image"]
    for key in _INT_SETTINGS:
        value = saved.get(key)
        # bool is a subclass of int, but is not a meaningful timeout.
        if type(value) is int and 0 <= value <= 1800:
            result[key] = value
    return result


def settings():
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        saved = {}
    return _validated_settings(saved)


def save_settings(value):
    result = {**settings(), **value}
    if result["image_device"] not in _IMAGE_DEVICES:
        raise ValueError("Invalid image device")
    if result["main_during_image"] not in _MAIN_POLICIES:
        raise ValueError("Invalid main model policy")
    for key in _INT_SETTINGS:
        if type(result[key]) is not int or not 0 <= result[key] <= 1800:
            raise ValueError(f"{key} must be an integer between 0 and 1800")
    result = {key: result[key] for key in DEFAULTS}
    with _STATE_LOCK:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
        temporary.replace(path)
    return result


def local_request(url, payload=None, timeout=3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                    headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def gpu_memory():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        total, used, free = [int(x.strip()) for x in result.stdout.strip().splitlines()[0].split(",")]
        return {"total_mib": total, "used_mib": used, "free_mib": free}
    except Exception:
        return None


def begin_task(kind, model, description, device="cpu"):
    task = {"id": uuid.uuid4().hex, "kind": kind, "model": model, "description": description[:180],
            "device": device, "status": "queued", "reason": "", "created_at": time.time()}
    with _STATE_LOCK:
        _TASKS.append(task)
        # Keep active jobs and at most 100 finished jobs.
        finished = [item for item in _TASKS if item["status"] in {"complete", "failed"}]
        for item in finished[:-100]:
            _TASKS.remove(item)
    return task["id"]


def update_task(task_id, **values):
    with _STATE_LOCK:
        for task in _TASKS:
            if task["id"] == task_id:
                task.update(values)
                break


def finish_task(task_id, error=None):
    update_task(task_id, status="failed" if error else "complete", reason=str(error or ""), finished_at=time.time())


def tasks():
    with _STATE_LOCK:
        return [dict(task) for task in reversed(_TASKS)]


def image_lease():
    try:
        value = json.loads((get_config_dir() / "data/gpu-image-lease.json").read_text(encoding="utf-8"))
        return value if value.get("expires_at", 0) > time.time() else {}
    except (OSError, ValueError):
        return {}


def main_model():
    import tomllib

    try:
        config = tomllib.loads((get_config_dir() / "config.toml").read_text(encoding="utf-8"))
        if config.get("engine", {}).get("default", "ollama") != "ollama":
            return ""
        intelligence = config.get("intelligence", {})
        return intelligence.get("model_chat") or intelligence.get("default_model", "")
    except (OSError, ValueError):
        return ""


def ram_memory():
    try:
        import psutil

        memory = psutil.virtual_memory()
        total, free = memory.total, memory.available
    except ImportError:
        if os.name != "nt":
            return None
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_physical", "available_physical", "total_page", "available_page",
                    "total_virtual", "available_virtual", "available_extended")]

        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            return None
        total, free = memory.total_physical, memory.available_physical
    return {"total_mib": total // 1048576, "used_mib": (total - free) // 1048576,
            "free_mib": free // 1048576}


def available_ram_mib():
    return (ram_memory() or {}).get("free_mib", 0)


def preload_main(model, device, num_ctx):
    return local_request(_OLLAMA_URL.rstrip("/") + "/api/generate", {
        "model": model, "stream": False, "keep_alive": "5m",
        "options": {"num_gpu": 0 if device == "cpu" else -1,
                    "num_ctx": num_ctx, "num_thread": 4},
    }, timeout=180)


@contextlib.contextmanager
def image_job(description, width=512, height=512):
    policy = settings()
    task_id = begin_task("image", "LCM Dreamshaper v7", description)
    with _IMAGE_LOCK:
        paused_voice = False
        device = "cpu"
        reason = ""
        required_mib = max(3000, int(3000 * int(width) * int(height) / (512 * 512)))
        lease_path = get_config_dir() / "data/gpu-image-lease.json"
        lease = {"task_id": task_id, "expires_at": time.time() + 1800}
        writer_locked = False
        main_moved = False
        restore_device = "gpu"
        main = ""
        num_ctx = 16384

        def write_lease():
            lease_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = lease_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(lease), encoding="utf-8")
            temporary.replace(lease_path)

        def restore_main(announce=True):
            nonlocal main_moved
            if main_moved:
                if announce:
                    update_task(task_id, status="waiting", reason="生图结束，恢复主模型设备")
                lease["main_device"] = restore_device
                write_lease()
                preload_main(main, restore_device, num_ctx)
                main_moved = False

        image_unloaded = True
        try:
            if policy["image_device"] != "cpu":
                device = "cuda"
                write_lease()
                update_task(task_id, status="waiting", device=device, reason="等待当前语音结束并释放语音显存")
                deadline = time.monotonic() + policy["voice_wait_seconds"]
                while True:
                    try:
                        health = local_request(_VOICE_URL + "/health")
                        if health.get("identity") != "jarvis-high-qwen-local-v1":
                            raise RuntimeError("Unexpected voice worker on port 3337")
                        local_request(_VOICE_URL + "/suspend", {}, timeout=5)
                        paused_voice = True
                        break
                    except urllib.error.HTTPError as exc:
                        if exc.code != 409:
                            raise
                        if time.monotonic() >= deadline:
                            if policy["image_device"] == "auto":
                                device = "cpu"
                                reason = "语音任务尚未结束，自动改用 CPU"
                                break
                            raise RuntimeError("语音仍在运行，等待 GPU 超时") from exc
                        time.sleep(0.3)
                    except (urllib.error.URLError, TimeoutError):
                        # There is no running voice worker to suspend.
                        break
                if device == "cuda" and policy["main_during_image"] == "cpu":
                    main = main_model()
                    if main:
                        update_task(task_id, status="waiting", reason="等待写作任务结束，腾出内存供主模型使用")
                        WRITER_LOCK.acquire()
                        writer_locked = True
                        resident = local_request(_OLLAMA_URL.rstrip("/") + "/api/ps").get("models", [])
                        for item in resident:
                            if item.get("name", "").startswith("jarvis-writer:"):
                                local_request(_OLLAMA_URL.rstrip("/") + "/api/generate",
                                              {"model": item["name"], "keep_alive": 0}, timeout=120)
                        original = next((item for item in resident if item.get("name") == main), None)
                        if original:
                            num_ctx = original.get("context_length") or num_ctx
                            restore_device = "gpu" if original.get("size_vram") else "cpu"
                        needs_migration = not original or bool(original.get("size_vram"))
                        if needs_migration and available_ram_mib() < 8192:
                            reason = "可用内存不足 8 GiB，主模型保留当前设备"
                            if policy["image_device"] == "cuda":
                                raise RuntimeError(reason + "；请释放内存或选择保留主模型设备")
                        else:
                            lease.update(main_model=main, main_device="cpu", num_ctx=num_ctx)
                            write_lease()
                            main_moved = needs_migration
                            update_task(task_id, status="waiting", reason="主模型切换到 CPU，释放 GPU 供生图")
                            preload_main(main, "cpu", num_ctx)
                            reason = "主模型在 CPU 保持可用，写作排队，GPU 用于生图"
                memory = gpu_memory()
                if not memory or memory["free_mib"] < required_mib:
                    if policy["image_device"] == "cuda":
                        raise RuntimeError(f"该尺寸生图需要约 {required_mib / 1024:.1f}GiB 空闲显存；主助手保持运行")
                    device = "cpu"
                    reason = "空闲显存不足，自动改用 CPU"
            if device == "cpu":
                restore_main()
                lease_path.unlink(missing_ok=True)
                if paused_voice:
                    local_request(_VOICE_URL + "/resume", {}, timeout=5)
                    paused_voice = False
                if writer_locked:
                    WRITER_LOCK.release()
                    writer_locked = False
            update_task(task_id, status="running", device=device, reason=reason, started_at=time.time())
            try:
                image_unloaded = device != "cuda"
                yield {"device": device, "idle_seconds": policy["cpu_image_idle_seconds"], "task_id": task_id}
            finally:
                # GPU weights must leave before queued voice work can resume.
                if device == "cuda":
                    local_request(_IMAGE_URL + "/unload", {}, timeout=30)
                    image_unloaded = True
                restore_main()
                if paused_voice:
                    lease_path.unlink(missing_ok=True)
                    local_request(_VOICE_URL + "/resume", {}, timeout=5)
                    paused_voice = False
                lease_path.unlink(missing_ok=True)
            finish_task(task_id)
        except Exception as exc:
            finish_task(task_id, exc)
            raise
        finally:
            try:
                if image_unloaded:
                    try:
                        restore_main(announce=False)
                    finally:
                        lease_path.unlink(missing_ok=True)
                        if paused_voice:
                            try:
                                local_request(_VOICE_URL + "/resume", {}, timeout=5)
                            except Exception:
                                pass
                # An unresponsive GPU worker retains its lease until expiry;
                # do not load voice/main weights over a possibly active job.
            finally:
                if writer_locked:
                    WRITER_LOCK.release()


def snapshot():
    services = {}
    for key, url in (("ollama", _OLLAMA_URL.rstrip("/") + "/api/ps"),
                     ("voice", _VOICE_URL + "/health"),
                     ("image", _IMAGE_URL + "/health")):
        try:
            services[key] = local_request(url)
        except Exception:
            services[key] = None
    ram = ram_memory()
    root = get_resource_dir()
    deployed = {"writer": (root / "models/creative/writer/download-manifest.json").is_file(),
                "image": (root / "models/creative/lcm-dreamshaper-v7/download-manifest.json").is_file()}
    return {"settings": settings(), "gpu": gpu_memory(), "ram": ram, "deployed": deployed,
            "services": services, "tasks": tasks()}
