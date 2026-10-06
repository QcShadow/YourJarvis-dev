"""Exercise an extracted installation's real server, HTML and chat endpoint."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

import tomllib


def smoke(root: Path):
    python = root / "src/.venv/Scripts/python.exe"
    config = root / "config.toml"
    assert python.is_file() and config.is_file()
    before = hashlib.sha256(config.read_bytes()).hexdigest()
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = {
        **os.environ,
        "OPENJARVIS_HOME": str(root),
        "PYTHONUTF8": "1",
        "JARVIS_SKIP_MODEL_PICK": "1",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }
    logs = root / "logs/server-smoke.log"
    with logs.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                str(python),
                "-m",
                "openjarvis.cli",
                "--quiet",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--engine",
                settings["engine"]["default"],
                "--agent",
                settings["agent"]["default_agent"],
                "--model",
                settings["intelligence"]["default_model"],
            ],
            cwd=root,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(90):
                try:
                    with urlopen(base + "/health", timeout=2) as response:
                        health = json.load(response)
                    if health["status"] == "ok":
                        break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(f"Server exited; see {logs}")
                    time.sleep(1)
            else:
                raise RuntimeError(f"Server not ready; see {logs}")
            with urlopen(base + "/", timeout=5) as response:
                assert b"<html" in response.read().lower()
            body = json.dumps(
                {
                    "model": settings["intelligence"]["default_model"],
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 4,
                    "stream": False,
                }
            ).encode()
            with urlopen(
                Request(
                    base + "/v1/chat/completions",
                    data=body,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=120,
            ) as response:
                result = json.load(response)
                assert result["choices"][0]["message"]["content"]
            assert hashlib.sha256(config.read_bytes()).hexdigest() == before
            print(
                json.dumps(
                    {"health": "ok", "html": "ok", "chat": "ok", "root": str(root)},
                    ensure_ascii=False,
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    smoke(parser.parse_args().root.resolve())
