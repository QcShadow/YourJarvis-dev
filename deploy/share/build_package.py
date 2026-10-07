"""Create a clean bootstrap ZIP from an explicit allowlist, never the data root."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

RUNTIME_FILES = (
    "runtime-state.ps1",
    "env.ps1",
    "jarvis.cmd",
    "jarvis.ps1",
    "start-gui.cmd",
    "start-gui.ps1",
    "stop-gui.cmd",
    "stop-gui.ps1",
    "start-ollama.cmd",
    "start-ollama.ps1",
    "ollama.cmd",
    "ollama.ps1",
    "setup-jarvis.cmd",
    "setup-jarvis.ps1",
)
EXCLUDED_PARTS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".cache",
    ".pytest_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".jsonl", ".log", ".pem"}


def tree_files(root: Path):
    for file in sorted(root.rglob("*")):
        relative = file.relative_to(root)
        if (
            file.is_file()
            and not file.is_symlink()
            and not EXCLUDED_PARTS.intersection(relative.parts)
            and file.suffix not in EXCLUDED_SUFFIXES
            and not file.name.startswith(".env")
        ):
            yield file


def package_entries(root: Path, *, lite=False, speech=False, desktop=False, desktop_directory=None):
    project = root / "src"
    share = project / "deploy/share"
    entries: dict[str, Path] = {}

    def add(file: Path, target: str):
        if not file.is_file():
            raise FileNotFoundError(f"Required package file missing: {file}")
        entries[target] = file

    # Source/data are intentionally separate; no owner's config, memories,
    # logs, credentials, WebView profile or existing Python venv is copied.
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE"):
        add(project / name, "src/" + name)
    source = project / "src/openjarvis"
    for file in tree_files(source):
        add(file, "src/src/openjarvis/" + file.relative_to(source).as_posix())
    for directory in ("scripts/install", "deploy/windows"):
        for file in tree_files(project / directory):
            add(file, "src/" + file.relative_to(project).as_posix())
    for name in RUNTIME_FILES:
        add(share / "runtime" / name, name)
    for name in (
        "install-jarvis.ps1",
        "install-jarvis.cmd",
        "install-worker.ps1",
        "install-speech.ps1",
    ):
        add(share / name, name)
    add(share / "configure_portable.py", "scripts/configure_portable.py")
    add(share / "smoke_installed.py", "scripts/smoke_installed.py")
    add(share / "verify_voice.py", "scripts/verify_voice.py")
    add(share / "configure_speech.py", "scripts/configure_speech.py")
    for name in ("qwen_tts_server.py", "qwen_voice_audio.py"):
        add(share / "voice" / name, "scripts/" + name)
    add(share / "README.zh-CN.md", "使用说明.md")
    if desktop:
        # Generated UI assets are ignored by Git; a clean snapshot must build them.
        if not (source / "server/static/index.html").is_file():
            raise FileNotFoundError(
                "Build the frontend before packaging the desktop release."
            )
        binaries = Path(desktop_directory) if desktop_directory else root / "dist/share-desktop"
        if not binaries.is_dir():
            binaries = root
        for name in (
            "JARVIS.exe",
            "JARVIS-Desktop.exe",
            "JARVIS.exe.config",
            "JARVIS-Desktop.exe.config",
            "Microsoft.Web.WebView2.Core.dll",
            "Microsoft.Web.WebView2.WinForms.dll",
            "WebView2Loader.dll",
            "app-version.json",
            "JARVIS-Install.exe",
            "JARVIS-Install.exe.config",
            "JARVIS-Resources.exe",
            "JARVIS-Spawn.exe",
            "JARVIS-Speech.exe",
            "JARVIS-Uninstall.exe",
        ):
            add(binaries / name, name)
        add(binaries / "resources.json", "resources.json")
    add(share / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")
    if lite:
        relative = "models/ollama/manifests/registry.ollama.ai/library/qwen2.5/0.5b"
        manifest = root / relative
        add(manifest, relative)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for layer in [data["config"], *data["layers"]]:
            digest = layer["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Invalid model digest.")
            blob = root / "models/ollama/blobs" / digest.replace(":", "-")
            with blob.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest[7:]:
                    raise ValueError(f"Model checksum mismatch: {blob.name}")
            add(blob, "models/ollama/blobs/" + blob.name)
    if speech:
        for name in ("model.int8.onnx", "tokens.txt", "LICENSE", "README.md"):
            relative = "models/speech/sensevoice/" + name
            add(root / relative, relative)
        relative = "cache/huggingface/hub/models--hexgrad--Kokoro-82M"
        for file in tree_files(root / relative):
            parts = file.relative_to(root / relative).parts
            if parts[0] in {"refs", "snapshots"}:
                add(file, file.relative_to(root).as_posix())
    return entries


def build_package(root: Path, output: Path, desktop_directory=None, **options):
    entries = package_entries(root, desktop_directory=desktop_directory, **options)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": 1,
        "kind": "bootstrap-source-package",
        "options": options,
        "requires": (
            "Windows x64, internet for Python/dependencies, Ollama for local LLM"
        ),
        "files": [],
    }
    # Exclusive creation keeps older release artifacts intact.
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for target, source in sorted(entries.items()):
            with source.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            archive.write(source, "JARVIS-Share/" + target)
            manifest["files"].append(
                {"path": target, "bytes": source.stat().st_size, "sha256": checksum}
            )
        archive.writestr(
            "JARVIS-Share/package-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--desktop-directory", type=Path)
    parser.add_argument(
        "--lite", action="store_true", help="Include only Qwen2.5 0.5B weights."
    )
    parser.add_argument(
        "--speech", action="store_true", help="Include Mandarin speech weights."
    )
    parser.add_argument(
        "--desktop", action="store_true", help="Include the built Windows launcher."
    )
    args = parser.parse_args()
    manifest = build_package(
        args.root.resolve(),
        args.output.resolve(),
        desktop_directory=args.desktop_directory,
        lite=args.lite,
        speech=args.speech,
        desktop=args.desktop,
    )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "files": len(manifest["files"]),
                "bytes": args.output.stat().st_size,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
