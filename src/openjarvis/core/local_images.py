"""Start and call the isolated local image worker without loading torch in Jarvis."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

from openjarvis.core.paths import get_resource_dir

URL = os.environ.get("JARVIS_IMAGE_URL", "http://127.0.0.1:3338")
IDENTITY = "jarvis-local-lcm-cpu-v1"
_LOCK = threading.Lock()
_PROCESS = None


def worker_health():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/health", timeout=2) as response:
            data = json.load(response)
        if data.get("identity") != IDENTITY:
            raise RuntimeError("Port 3338 is occupied by another service")
        return data
    except (urllib.error.URLError, TimeoutError):
        return None


def ensure_worker():
    global _PROCESS
    with _LOCK:
        health = worker_health()
        if health is not None:
            if not health.get("ready"):
                raise RuntimeError("Local image weights are not downloaded")
            return health
        root = get_resource_dir()
        python = root / "runtimes/creative-image/.venv/Scripts/python.exe"
        script = root / "scripts/local_image_server.py"
        if not python.is_file() or not script.is_file():
            raise RuntimeError("Local image runtime is missing; run setup-creative.cmd")
        if not (root / "models/creative/lcm-dreamshaper-v7/download-manifest.json").is_file():
            raise RuntimeError("Local image model is missing; run setup-creative.cmd")
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(HF_HUB_OFFLINE="1", PYTHONUNBUFFERED="1", PYTHONUTF8="1")
        with (logs / "local-image-worker.log").open("ab") as log:
            _PROCESS = subprocess.Popen(
                [str(python), str(script)], cwd=str(root), env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            health = worker_health()
            if health and health.get("ready"):
                return health
            if _PROCESS.poll() is not None:
                raise RuntimeError("Local image worker exited; check logs/local-image-worker.log")
            time.sleep(0.2)
        raise RuntimeError("Local image worker startup timed out")


def generate_image(**params):
    ensure_worker()
    from openjarvis.core.model_scheduler import image_job

    with image_job(str(params.get("prompt", "")), params.get("width", 512), params.get("height", 512)) as allocation:
        return _generate_image(**params, device=allocation["device"], idle_seconds=allocation["idle_seconds"])


def _generate_image(**params):
    request = urllib.request.Request(
        URL + "/generate", data=json.dumps(params).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local image worker: {detail}") from exc
