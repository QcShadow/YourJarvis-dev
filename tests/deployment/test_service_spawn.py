"""A launched backend must survive its parent's capture pipes closing."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process handles")


def test_detached_service_does_not_keep_parent_capture_open(tmp_path):
    source = Path(__file__).parents[2] / "deploy/yourjarvis/launcher/Spawn.cs"
    launcher = tmp_path / "spawn.exe"
    subprocess.run([r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe", "/nologo", "/platform:x64", "/target:exe", "/reference:System.Web.Extensions.dll", f"/out:{launcher}", str(source)], check=True, capture_output=True)
    server = tmp_path / "service with spaces.py"
    server.write_text("""import http.server, json, sys
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps(sys.argv[2:]).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
http.server.HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
""", encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    arguments = ['space and "quote"', 'trailing\\', '中文目录']
    launched = subprocess.run([str(launcher), str(tmp_path), sys.executable, str(tmp_path / "stdout.log"), str(tmp_path / "stderr.log"), str(server), str(port), *arguments], capture_output=True, timeout=5)
    assert launched.returncode == 0, launched.stderr
    pid = json.loads(launched.stdout)["pid"]
    opener = build_opener(ProxyHandler({}))
    try:
        for _ in range(30):
            try:
                with opener.open(f"http://127.0.0.1:{port}", timeout=1) as response:
                    assert json.load(response) == arguments
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail((tmp_path / "stderr.log").read_text())
    finally:
        subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
