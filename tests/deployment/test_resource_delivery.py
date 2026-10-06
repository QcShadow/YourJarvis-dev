"""Real native downloader: fallback, resume, integrity and safe extraction."""

import hashlib
import http.server
import io
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native installer")


@pytest.fixture(scope="module")
def executable(tmp_path_factory):
    output = tmp_path_factory.mktemp("native-downloader") / "resources.exe"
    source = Path(__file__).parents[2] / "deploy/yourjarvis/launcher/ResourceFetch.cs"
    subprocess.run(
        [
            r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
            "/nologo",
            "/target:exe",
            f"/out:{output}",
            "/reference:System.Net.Http.dll",
            "/reference:System.Web.Extensions.dll",
            "/reference:System.IO.Compression.dll",
            "/reference:System.IO.Compression.FileSystem.dll",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    return output


def run(executable, root, archive, bases):
    item = {
        "name": "fixture.zip.001",
        "bytes": len(archive),
        "sha256": hashlib.sha256(archive).hexdigest(),
    }
    manifest = root / "resources.json"
    manifest.write_text(
        json.dumps(
            {
                "pythonHome": "runtimes/python/test",
                "baseUrls": bases,
                "packs": {"fixture": {**item, "parts": [item]}},
            }
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [str(executable), str(root), str(manifest), "fixture"],
        capture_output=True,
        timeout=20,
    )


def archive(name="models/speech/fixture/tokens.txt"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr(name, "tokens")
    return output.getvalue()


def test_resume_and_channel_fallback(executable, tmp_path):
    data = archive()
    offsets = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/bad/"):
                self.send_error(503)
                return
            offset = int(
                self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0]
            )
            offsets.append(offset)
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(len(data) - offset))
            if offset:
                self.send_header(
                    "Content-Range", f"bytes {offset}-{len(data) - 1}/{len(data)}"
                )
            self.end_headers()
            self.wfile.write(data[offset:])

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cache = tmp_path / "cache/downloads"
    cache.mkdir(parents=True)
    (cache / "fixture.zip.001.part").write_bytes(data[:19])
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        result = run(executable, tmp_path, data, [base + "/bad", base])
        assert result.returncode == 0, result.stdout
        assert offsets == [19]
        assert (tmp_path / "models/speech/fixture/tokens.txt").read_text() == "tokens"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "name", ["../outside.txt", "models/../credentials.toml", "config.toml"]
)
def test_resource_cannot_overwrite_user_configuration(executable, tmp_path, name):
    data = archive(name)
    cache = tmp_path / "cache/downloads"
    cache.mkdir(parents=True)
    (cache / "fixture.zip.001").write_bytes(data)
    result = run(executable, tmp_path, data, [])
    assert result.returncode != 0
    assert not (tmp_path / "credentials.toml").exists()
    assert not (tmp_path / "config.toml").exists()
