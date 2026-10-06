"""Build the legacy text prototype; use build_full_package.py for full Link."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import zipfile
from pathlib import Path


def build(root: Path, directory: Path, output: Path):
    if directory.exists() or output.exists():
        raise FileExistsError("Choose new output paths; existing files are preserved.")
    spec = importlib.util.spec_from_file_location(
        "share_package", root / "src/deploy/share/build_package.py"
    )
    share = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(share)
    entries = {
        name: path
        for name, path in share.package_entries(root, lite=True).items()
        if name.startswith("models/")
    }
    client = root / "src/deploy/friends-client"
    palettes_text = (root / "src/frontend/src/lib/palettes.ts").read_text("utf-8")
    palettes = {}
    for match in re.finditer(
        r"(\w+): \{ label: '([^']+)', light: (\[[^\]]+\]), dark: (\[[^\]]+\])",
        palettes_text,
    ):
        key, label, light, dark = match.groups()
        palettes[key] = {
            "label": label,
            "light": json.loads(light.replace("'", '"')),
            "dark": json.loads(dark.replace("'", '"')),
        }
    if "mcu" not in palettes:
        raise ValueError("Cannot read the main app's palette definitions")
    palette_file = client / "client/palette-data.js"
    palette_file.write_text(
        "window.jarvisPalettes=" + json.dumps(palettes, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    for file in share.tree_files(client / "client"):
        entries["client/" + file.relative_to(client / "client").as_posix()] = file
    entries["使用说明.md"] = client / "README.zh-CN.md"
    entries["联网与依赖清单.md"] = client / "DEPENDENCIES.zh-CN.md"
    entries["THIRD_PARTY_NOTICES.md"] = client / "THIRD_PARTY_NOTICES.md"
    entries["LICENSE"] = root / "src/LICENSE"
    entries["source/JARVIS-Link.cs"] = root / "launcher/FriendsDesktop.cs"
    entries["打开JARVIS-Link.cmd"] = client / "打开JARVIS-Link.cmd"
    for name in (
        "JARVIS-Link.exe",
        "JARVIS-Link.exe.config",
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebView2Loader.dll",
        "app-version.json",
    ):
        entries[name] = root / "dist/link-desktop" / name
    entries["runtimes/ollama/ollama.exe"] = root / "runtimes/ollama/ollama.exe"
    entries["runtimes/ollama/LICENSE"] = client / "OLLAMA-LICENSE"
    for file in (root / "runtimes/ollama/lib/ollama").iterdir():
        if file.is_file():
            entries["runtimes/ollama/lib/ollama/" + file.name] = file
    runtime = root / (
        "runtimes/webview2-fixed-154.0.4258.48/"
        "Microsoft.WebView2.FixedVersionRuntime.154.0.4258.48.x64"
    )
    if not (runtime / "msedgewebview2.exe").is_file():
        raise FileNotFoundError("Official fixed WebView2 runtime missing")
    for file in share.tree_files(runtime):
        entries["runtimes/webview2/" + file.relative_to(runtime).as_posix()] = file
    directory.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": 1,
        "kind": "jarvis-link-offline-cpu",
        "requires": "Windows 10 22H2 / Windows 11 x64, .NET Framework 4.8",
        "files": [],
    }
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, source in sorted(entries.items()):
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            with source.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            archive.write(source, "JARVIS-Link/" + name)
            manifest["files"].append(
                {"path": name, "bytes": source.stat().st_size, "sha256": checksum}
            )
        text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (directory / "package-manifest.json").write_text(text, encoding="utf-8")
        archive.writestr("JARVIS-Link/package-manifest.json", text)
    return {
        "directory": str(directory),
        "package": str(output),
        "bytes": output.stat().st_size,
        "files": len(entries),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.root.resolve(), args.directory.resolve(), args.output.resolve()),
            ensure_ascii=False,
        )
    )
