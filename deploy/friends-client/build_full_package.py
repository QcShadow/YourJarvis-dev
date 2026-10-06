"""Bundle the same full application, a CPU model and all offline runtimes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path


def runtime_files(directory):
    for file in sorted(directory.rglob("*")):
        parts = file.relative_to(directory).parts
        if file.is_file() and not file.is_symlink() and "__pycache__" not in parts:
            if file.suffix in {".pyc", ".pyo"} or file.name == "direct_url.json":
                continue
            if any(
                part.startswith(("_editable_impl_openjarvis", "_virtualenv"))
                for part in parts
            ):
                continue
            yield file


def build(root, directory, output, site_packages, browser_runtime, voice_site_packages=None):
    if directory.exists() or output.exists():
        raise FileExistsError(
            "Choose new release paths; existing user data is preserved"
        )
    spec = importlib.util.spec_from_file_location(
        "share", root / "src/deploy/share/build_package.py"
    )
    share = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(share)
    entries = {
        name: path
        for name, path in share.package_entries(root, lite=True, speech=True).items()
        if name.startswith(("src/src/openjarvis/", "models/", "cache/huggingface/"))
    }
    directory.mkdir(parents=True)
    # Freeze the complete source together before slow runtime compression.
    # Another development chat may add routes while this release is building.
    for name, source in list(entries.items()):
        if name.startswith("src/src/openjarvis/"):
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            entries[name] = target
    client = root / "src/deploy/friends-client"
    for name, source in {
        "使用说明.md": "README-Jarvis-Voice.zh-CN.md" if voice_site_packages else "README-Full.zh-CN.md",
        "联网与依赖清单.md": "DEPENDENCIES-Full.zh-CN.md",
        "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
        "打开JARVIS-Link.cmd": "打开JARVIS-Link.cmd",
        "scripts/portable_backend.py": "portable_backend.py",
    }.items():
        entries[name] = client / source
    entries["LICENSE"] = root / "src/LICENSE"
    entries["source/JARVIS-Link.cs"] = root / "launcher/LinkDesktop.cs"
    entries["src/frontend/src-tauri/icons/icon.ico"] = (
        root / "src/frontend/src-tauri/icons/icon.ico"
    )
    for file in share.tree_files(root / "models/speech/whisper-small.en"):
        if ".cache" not in file.parts:
            entries[
                "models/speech/whisper-small.en/"
                + file.relative_to(root / "models/speech/whisper-small.en").as_posix()
            ] = file
    for file in runtime_files(
        root / "runtimes/python/cpython-3.12.14-windows-x86_64-none"
    ):
        entries[
            "runtimes/python/"
            + file.relative_to(
                root / "runtimes/python/cpython-3.12.14-windows-x86_64-none"
            ).as_posix()
        ] = file
    for file in runtime_files(site_packages):
        entries[
            "runtimes/python/Lib/site-packages/"
            + file.relative_to(site_packages).as_posix()
        ] = file
    if voice_site_packages:
        for folder in ("models/speech/qwen3-tts-0.6b-base", "models/piper/jarvis-high"):
            for file in runtime_files(root / folder):
                if ".cache" not in file.parts and file.name != ".gitattributes":
                    entries[folder + "/" + file.relative_to(root / folder).as_posix()] = file
        for name in ("qwen_tts_server.py", "qwen_voice_audio.py"):
            entries["scripts/" + name] = root / "scripts" / name
        interpreter = root / "runtimes/python/cpython-3.12.14-windows-x86_64-none"
        for file in runtime_files(interpreter):
            entries["runtimes/qwen-tts/python/" + file.relative_to(interpreter).as_posix()] = file
        for file in runtime_files(voice_site_packages):
            entries["runtimes/qwen-tts/python/Lib/site-packages/" + file.relative_to(voice_site_packages).as_posix()] = file
        for name in ("voice_settings.json", "bundled-voice.json", "requirements.cpu.lock.txt"):
            entries["runtimes/qwen-tts/" + name] = client / "jarvis-voice" / name
        for key in (
            "runtimes/qwen-tts/python/python.exe",
            "runtimes/qwen-tts/python/Lib/site-packages/qwen_tts/__init__.py",
            "models/speech/qwen3-tts-0.6b-base/model.safetensors",
            "models/speech/qwen3-tts-0.6b-base/speech_tokenizer/model.safetensors",
            "models/piper/jarvis-high/reference.wav",
            "models/piper/jarvis-high/jarvis-high.onnx",
        ):
            if key not in entries or not entries[key].is_file():
                raise FileNotFoundError("Required bundled voice asset: " + key)
    # Rust-backed document memory and core tools must work offline too. Copy
    # only this compiled package, never the developer's complete virtualenv.
    native_root = root / "src/.venv/Lib/site-packages"
    for folder in ("openjarvis_rust", "openjarvis_rust-0.1.0.dist-info"):
        for file in runtime_files(native_root / folder):
            entries[
                "runtimes/python/Lib/site-packages/"
                + file.relative_to(native_root).as_posix()
            ] = file
    if not any(
        name.endswith(".pyd") and "/openjarvis_rust/" in name for name in entries
    ):
        raise FileNotFoundError("Native memory/tool extension is required")
    for file in runtime_files(browser_runtime):
        if ".links" not in file.relative_to(browser_runtime).parts:
            entries[
                "runtimes/playwright/" + file.relative_to(browser_runtime).as_posix()
            ] = file
    for file in (root / "dist/link-full-desktop").iterdir():
        if file.is_file():
            entries[file.name] = file
    entries["runtimes/ollama/ollama.exe"] = root / "runtimes/ollama/ollama.exe"
    entries["runtimes/ollama/LICENSE"] = client / "OLLAMA-LICENSE"
    for file in (root / "runtimes/ollama/lib/ollama").iterdir():
        if file.is_file():
            entries["runtimes/ollama/lib/ollama/" + file.name] = file
    runtime = (
        root
        / "runtimes/webview2-fixed-154.0.4258.48"
        / "Microsoft.WebView2.FixedVersionRuntime.154.0.4258.48.x64"
    )
    for file in runtime_files(runtime):
        entries["runtimes/webview2/" + file.relative_to(runtime).as_posix()] = file
    for key in (
        "runtimes/python/python.exe",
        "runtimes/webview2/msedgewebview2.exe",
        "src/src/openjarvis/server/static/index.html",
    ):
        if key not in entries or not entries[key].is_file():
            raise FileNotFoundError(key)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": 1,
        "kind": "jarvis-link-full-offline-cpu-jarvis-zh" if voice_site_packages else "jarvis-link-full-offline-cpu",
        "requires": "Windows 10 22H2 / 11 x64, .NET Framework 4.8",
        "files": [],
    }
    # Copy all allowlisted assets before compression. ZIP only these frozen
    # entries, never rescan a launched application's private data directories.
    for name, source in sorted(entries.items()):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            shutil.copyfile(source, target)
        entries[name] = target
    print(
        json.dumps({"stage_ready": str(directory), "files": len(entries)}), flush=True
    )
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, source in sorted(entries.items()):
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            archive.write(source, "JARVIS-Link/" + name)
            manifest["files"].append(
                {"path": name, "bytes": source.stat().st_size, "sha256": digest}
            )
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        (directory / "package-manifest.json").write_text(content, encoding="utf-8")
        archive.writestr("JARVIS-Link/package-manifest.json", content)
    return {
        "package": str(output),
        "directory": str(directory),
        "bytes": output.stat().st_size,
        "files": len(entries),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "directory", "output", "site-packages", "browser-runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jarvis-voice-site-packages", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.root.resolve(),
                args.directory.resolve(),
                args.output.resolve(),
                args.site_packages.resolve(),
                args.browser_runtime.resolve(),
                args.jarvis_voice_site_packages.resolve() if args.jarvis_voice_site_packages else None,
            ),
            ensure_ascii=False,
        )
    )
