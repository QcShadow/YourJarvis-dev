"""Start the complete application with portable, recipient-owned state."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen


def choose_port(previous: int | None = None) -> int:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", previous or 0))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def configure_environment(root: Path):
    # Set before importing config: every default DB/memory path is per client.
    for key, value in {
        "OPENJARVIS_HOME": root / "data/state",
        "OPENJARVIS_CONFIG": root / "data/state/config.toml",
        "OPENJARVIS_RESOURCE_ROOT": root,
        "HF_HOME": root / "cache/huggingface",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONUTF8": "1",
        "JARVIS_PORTABLE_CLIENT": "1",
        "JARVIS_SKIP_MODEL_PICK": "1",
        "PLAYWRIGHT_BROWSERS_PATH": root / "runtimes/playwright",
        "TOKENIZERS_PARALLELISM": "false",
        "OLLAMA_MODELS": root / "models/ollama",
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_VULKAN": "false",
    }.items():
        os.environ[key] = str(value)
    # Do not accidentally use the launcher's inherited owner/cloud keys.
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "JARVIS_LLM_API_KEY",
        "OPENJARVIS_API_KEY",
    ):
        os.environ.pop(key, None)
    os.environ["PATH"] = str(root / "runtimes/python") + os.pathsep + os.environ["PATH"]
    # Windows system proxy settings can otherwise send loopback httpx calls
    # through a proxy. Keep local services direct; preserve external proxies.
    bypass = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    os.environ["NO_PROXY"] = ",".join(
        filter(None, [bypass, "127.0.0.1", "localhost", "::1"])
    )
    sys.path.insert(0, str(root / "src/src"))
    from openjarvis.core.credentials import TOOL_CREDENTIALS

    for names in TOOL_CREDENTIALS.values():
        for key in names:
            os.environ.pop(key, None)


def initial_configuration(root: Path, local_url: str) -> str:
    from openjarvis.core.deployment import configuration_text

    content = configuration_text(root, full_features=True, base_url=local_url)
    if (root / "runtimes/qwen-tts/bundled-voice.json").is_file():
        import tomlkit

        doc = tomlkit.parse(content)
        doc["speech"]["tts_backend"] = "jarvis"
        doc["speech"]["voice_id"] = "jarvis-high"
        doc["deployment"]["voice_profile"] = "jarvis-multilingual"
        content = tomlkit.dumps(doc)
    return content


def run(root: Path, ready: Path):
    configure_environment(root)
    from openjarvis.core.config import load_config
    from openjarvis.security.file_utils import secure_write_text

    state = root / "data/state"
    state.mkdir(parents=True, exist_ok=True)
    ports_path = root / "data/ports.json"
    previous = json.loads(ports_path.read_text()) if ports_path.exists() else {}
    ports = {}
    for key in ("server", "ollama", "voice", "image"):
        port = choose_port(previous.get(key))
        while port in ports.values():
            port = choose_port()
        ports[key] = port
    # Do not assign the same temporarily free port to both services.
    while ports["server"] == ports["ollama"]:
        ports["ollama"] = choose_port()
    ports_path.write_text(json.dumps(ports), encoding="utf-8")
    local_url = "http://127.0.0.1:" + str(ports["ollama"])
    old_local_url = "http://127.0.0.1:" + str(previous.get("ollama", ports["ollama"]))
    os.environ["JARVIS_LOCAL_OLLAMA_URL"] = local_url
    os.environ["OLLAMA_HOST"] = local_url
    os.environ["JARVIS_VOICE_URL"] = "http://127.0.0.1:" + str(ports["voice"])
    os.environ["JARVIS_IMAGE_URL"] = "http://127.0.0.1:" + str(ports["image"])
    config_path = state / "config.toml"
    if not config_path.exists():
        secure_write_text(
            config_path,
            initial_configuration(root, local_url),
        )
    else:
        # Update only relocated bundled asset paths / our managed Ollama port;
        # preserve the user's prompts, tools, memories and external endpoints.
        import tomlkit

        doc = tomlkit.parse(config_path.read_text(encoding="utf-8-sig"))
        previous_root = doc.get("deployment", {}).get("resource_root", str(root))
        ollama = doc.get("engine", {}).get("ollama", {})
        if ollama.get("host") == old_local_url:
            ollama["host"] = local_url
        for key, folder in (
            ("chinese_model", "sensevoice"),
            ("english_model", "whisper-small.en"),
        ):
            saved = doc.get("speech", {}).get(key, "")
            if saved == str(Path(previous_root) / "models/speech" / folder):
                doc["speech"][key] = str(root / "models/speech" / folder)
        doc.setdefault("deployment", {})["resource_root"] = str(root)
        secure_write_text(config_path, tomlkit.dumps(doc))
    cfg = load_config(config_path)
    ollama_process = None
    if cfg.engine.default == "ollama" and cfg.engine.ollama.host == local_url:
        logs = root / "logs"
        logs.mkdir(exist_ok=True)
        ollama_process = subprocess.Popen(
            [str(root / "runtimes/ollama/ollama.exe"), "serve"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=(logs / "ollama.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for _ in range(150):
            if ollama_process.poll() is not None:
                raise RuntimeError("Bundled Ollama exited; see logs/ollama.log")
            try:
                with urlopen(local_url + "/api/tags", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            ollama_process.terminate()
            raise RuntimeError("Bundled Ollama startup timed out")
    url = "http://127.0.0.1:" + str(ports["server"])

    # Native shell receives readiness only after the complete server is healthy.
    def publish_ready():
        for _ in range(600):
            try:
                with urlopen(url + "/v1/deployment/bootstrap", timeout=0.5) as response:
                    if response.status == 200:
                        ready.write_text(json.dumps({"url": url}), encoding="utf-8")
                        return
            except OSError:
                time.sleep(0.2)

    threading.Thread(target=publish_ready, daemon=True).start()
    from openjarvis.cli import cli

    try:
        cli.main(
            args=[
                "--quiet",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(ports["server"]),
            ]
        )
    finally:
        if ollama_process and ollama_process.poll() is None:
            ollama_process.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.ready.resolve())
