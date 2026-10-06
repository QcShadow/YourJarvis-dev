"""Exercise the same supervised backend that the installed desktop launches."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import tomllib


def smoke(root: Path):
    python = root / "src/.venv/Scripts/python.exe"
    config = root / "config.toml"
    before = hashlib.sha256(config.read_bytes()).hexdigest()
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    runtime = json.loads(subprocess.check_output(
        [str(python), "-c", "import sys,json; print(json.dumps([sys.executable,sys._base_executable,sys.base_prefix]))"],
        cwd=root, env={**os.environ, "PYTHONUTF8": "1"}, encoding="utf-8",
    ))
    if not all(Path(path).resolve().is_relative_to(root) for path in runtime):
        raise RuntimeError("Python 启动器仍指向安装目录外，请重新修复运行环境。")
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    opener = build_opener(ProxyHandler({}))
    headers = {}
    api_key = settings.get("server", {}).get("auth", {}).get("api_key", "")
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    try:
        started = subprocess.run(command + [str(root / "start-gui.ps1"), "-NoBrowser"], cwd=root, capture_output=True, timeout=300)
        (root / "logs/server-smoke.log").write_bytes(started.stdout + started.stderr)
        if started.returncode:
            raise RuntimeError("正式后台启动失败，请查看 logs/server-smoke.log。")
        state = json.loads((root / "logs/gui-runtime.json").read_text(encoding="utf-8-sig"))
        base = state["url"]
        with opener.open(Request(base + "/health", headers=headers), timeout=5) as response:
            assert response.headers.get("X-Jarvis-Instance") == state["instance"]
            assert json.load(response)["status"] == "ok"
        with opener.open(Request(base + "/", headers=headers), timeout=5) as response:
            assert b"<html" in response.read().lower()
        body = json.dumps({"model": settings["intelligence"]["default_model"], "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 4, "stream": False}).encode()
        with opener.open(Request(base + "/v1/chat/completions", data=body, headers={**headers, "Content-Type": "application/json"}), timeout=180) as response:
            assert json.load(response)["choices"][0]["message"]["content"]
        assert hashlib.sha256(config.read_bytes()).hexdigest() == before
        print(json.dumps({"health": "ok", "html": "ok", "chat": "ok", "runtime_paths": runtime, "url": base}, ensure_ascii=False))
    finally:
        subprocess.run(command + [str(root / "stop-gui.ps1")], cwd=root, capture_output=True, timeout=60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    smoke(parser.parse_args().root.resolve())
