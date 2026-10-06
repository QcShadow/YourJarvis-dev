"""Verify every release entry against its manifest and detect private state."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def verify(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifests = [name for name in names if name.endswith("/package-manifest.json")]
        if len(manifests) != 1:
            raise ValueError("Expected one package manifest")
        manifest_name = manifests[0]
        prefix = manifest_name.removesuffix("package-manifest.json")
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        manifest = json.loads(archive.read(manifest_name))
        expected = {prefix + item["path"] for item in manifest["files"]}
        if set(names) != expected | {manifest_name}:
            raise ValueError("ZIP entries differ from the manifest")
        for item in manifest["files"]:
            relative = PurePosixPath(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe archive path")
            if (
                relative.name.lower()
                in {
                    "config.toml",
                    "credentials.toml",
                    "friends-members.json",
                    "soul.md",
                    "user.md",
                    "memory.md",
                }
                or relative.parts[0] in {"logs", "memory"}
                or any(part in {".venv", "node_modules"} for part in relative.parts)
            ):
                raise ValueError(f"Private state in ZIP: {relative}")
            name = prefix + item["path"]
            if archive.getinfo(name).file_size != item["bytes"]:
                raise ValueError(f"File size mismatch: {name}")
            with archive.open(name) as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != item["sha256"]:
                raise ValueError(f"Checksum mismatch: {name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )
    return {
        "package": str(path),
        "bytes": path.stat().st_size,
        "files": len(expected),
        "sha256": digest,
        "verified": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args()
    for package in args.packages:
        print(json.dumps(verify(package), ensure_ascii=False))
