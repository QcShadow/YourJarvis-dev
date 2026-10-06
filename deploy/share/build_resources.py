"""Publish only explicit Windows runtime/model files, split into resumable parts."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_entries(environment: Path):
    for file in sorted(environment.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(environment)
        if "__pycache__" in rel.parts or file.suffix in {".pyc", ".pyo"}:
            continue
        if file.name in {
            "pyvenv.cfg",
            "direct_url.json",
            "_editable_impl_openjarvis.pth",
        }:
            continue
        if rel.parts[0] == "Scripts" and file.name not in {"python.exe", "pythonw.exe"}:
            continue
        yield file, "src/.venv/" + rel.as_posix()


def tree(directory: Path, target: str):
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    for file in sorted(directory.rglob("*")):
        if (
            file.is_file()
            and "__pycache__" not in file.parts
            and ".cache" not in file.parts
        ):
            yield file, target + "/" + file.relative_to(directory).as_posix()


def split_pack(name: str, entries, output: Path, *, part_bytes=90 * 1024 * 1024):
    archive = output / (name + ".zip")
    with zipfile.ZipFile(
        archive, "x", zipfile.ZIP_DEFLATED, compresslevel=1
    ) as zip_file:
        for file, target in entries:
            if not file.is_file():
                raise FileNotFoundError(file)
            zip_file.write(file, target)
    parts = []
    with archive.open("rb") as stream:
        index = 1
        while data := stream.read(part_bytes):
            path = output / f"{name}.zip.{index:03}"
            with path.open("xb") as part:
                part.write(data)
            parts.append({"name": path.name, "bytes": len(data), "sha256": sha(path)})
            index += 1
    result = {"bytes": archive.stat().st_size, "sha256": sha(archive), "parts": parts}
    print(
        json.dumps({"pack": name, "bytes": result["bytes"], "parts": len(parts)}),
        flush=True,
    )
    return result


def model_entries(root: Path, name: str, tag: str):
    relative = f"models/ollama/manifests/registry.ollama.ai/library/{name}/{tag}"
    manifest = root / relative
    yield manifest, relative
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for layer in [data["config"], *data["layers"]]:
        digest = layer["digest"]
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("Invalid Ollama digest")
        relative = "models/ollama/blobs/" + digest.replace(":", "-")
        file = root / relative
        if sha(file) != digest[7:]:
            raise ValueError(f"Model digest mismatch: {file}")
        yield file, relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--text-env", type=Path, required=True)
    parser.add_argument("--voice-env", type=Path, required=True)
    parser.add_argument("--python-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="0.1.3")
    args = parser.parse_args()
    root, output = args.root, args.output
    output.mkdir(parents=True, exist_ok=True)
    python_home = "runtimes/python/" + args.python_home.name
    manifest = {
        "format": 1,
        "version": args.version,
        "pythonHome": python_home,
        "baseUrls": [
            f"https://gitee.com/QcShadow/your-jarvis-link/releases/download/v{args.version}",
            f"https://github.com/QcShadow/YourJarvis-link/releases/download/v{args.version}",
        ],
        "packs": {},
    }
    sources = {
        "python": list(tree(args.python_home, python_home)),
        "runtime-text": list(runtime_entries(args.text_env)),
        "runtime-voice": list(runtime_entries(args.voice_env)),
        "llm-lite": list(model_entries(root, "qwen2.5", "0.5b")),
        "ollama-cpu": [
            (root / "runtimes/ollama/ollama.exe", "runtimes/ollama/ollama.exe")
        ],
        "speech-zh": [],
        "speech-en": list(
            tree(
                root / "models/speech/whisper-small.en",
                "models/speech/whisper-small.en",
            )
        ),
    }
    ollama = root / "runtimes/ollama/lib/ollama"
    sources["ollama-cpu"] += [
        (file, "runtimes/ollama/lib/ollama/" + file.name)
        for file in sorted(ollama.iterdir())
        if file.is_file()
    ]
    sources["ollama-cpu"].append((output / "OLLAMA-LICENSE", "runtimes/ollama/LICENSE"))
    for name in ("model.int8.onnx", "tokens.txt", "LICENSE", "README.md"):
        relative = "models/speech/sensevoice/" + name
        sources["speech-zh"].append((root / relative, relative))
    hf = root / "cache/huggingface/hub/models--hexgrad--Kokoro-82M"
    revision = (hf / "refs/main").read_text().strip()
    for name in (
        "config.json",
        "kokoro-v1_0.pth",
        "README.md",
        "VOICES.md",
        "voices/zm_yunjian.pt",
        "voices/zf_xiaoxiao.pt",
        "voices/bm_george.pt",
    ):
        file = hf / "snapshots" / revision / name
        sources["speech-zh"].append((file, file.relative_to(root).as_posix()))
    sources["speech-zh"].append(
        (hf / "refs/main", (hf / "refs/main").relative_to(root).as_posix())
    )
    sources["speech-zh"].append(
        (
            root / "src/LICENSE",
            f"cache/huggingface/hub/models--hexgrad--Kokoro-82M/snapshots/{revision}/LICENSE",
        )
    )
    webview = output / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    if webview.is_file():
        sources["webview2"] = [(webview, "cache/installers/" + webview.name)]
    for name, entries in sources.items():
        manifest["packs"][name] = split_pack(name, entries, output)
        repository = (
            "your-jarvis-runtime"
            if name in {"python", "runtime-text", "runtime-voice"}
            else "your-jarvis-speech"
            if name.startswith("speech-")
            else "your-jarvis-link"
        )
        manifest["packs"][name]["baseUrls"] = [
            f"https://gitee.com/QcShadow/{repository}/releases/download/v{args.version}",
            manifest["baseUrls"][1],
        ]
    (output / "resources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
