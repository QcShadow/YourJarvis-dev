"""Relocation must check the base executable, not just sys.executable."""
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from test_resource_delivery import archive, executable, run  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows portable runtime")


def test_stock_launcher_replaces_absolute_uv_redirector(executable, tmp_path):
    resources = Path(__file__).parents[3] / "dist/resources-0.1.3"
    if not (resources / "python.zip").exists():
        pytest.skip("Release Python fixture unavailable")
    with zipfile.ZipFile(resources / "python.zip") as source:
        prefix = "runtimes/python/cpython-3.12.14-windows-x86_64-none/"
        for entry in source.infolist():
            target = tmp_path / entry.filename.replace(prefix, "runtimes/python/test/")
            if not entry.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(entry))
    environment = tmp_path / "src/.venv"
    (environment / "Scripts").mkdir(parents=True)
    (environment / "Lib/site-packages").mkdir(parents=True)
    (environment / "Scripts/python.exe").write_bytes(b"old redirector embeds nonexistent builder path")
    data = archive()
    cache = tmp_path / "cache/downloads"
    cache.mkdir(parents=True)
    (cache / "fixture.zip.001").write_bytes(data)
    result = run(executable, tmp_path, data, [])
    assert result.returncode == 0, result.stdout
    paths = json.loads(subprocess.check_output([
        str(environment / "Scripts/python.exe"), "-c",
        "import sys,json; print(json.dumps([sys.executable,sys._base_executable,sys.base_prefix]))",
    ]))
    assert all(Path(path).resolve().is_relative_to(tmp_path) for path in paths)


@pytest.mark.parametrize("bad", ["root", "started", "path"])
def test_shutdown_does_not_kill_foreign_or_reused_pid(tmp_path, bad):
    root = Path(__file__).parents[2]
    helper = root / "deploy/share/runtime/runtime-state.ps1"
    script = tmp_path / "ownership.ps1"
    script.write_text(f"""
. '{helper}'
$script:JarvisRoot = '{tmp_path}'
$owned = Get-Process -Id $PID
$state = @{{root=$script:JarvisRoot;pid=$PID;started=[string]$owned.StartTime.ToUniversalTime().Ticks}}
$executable = $owned.Path
if ('{bad}' -eq 'root') {{ $state.root = 'C:\\foreign' }}
if ('{bad}' -eq 'started') {{ $state.started = '1' }}
if ('{bad}' -eq 'path') {{ $executable = 'C:\\foreign\\python.exe' }}
if (Get-OwnedJarvisProcess $state $executable) {{ exit 8 }}
exit 0
""", encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True)
    assert result.returncode == 0, result.stderr
