"""Exercise the native parser using its actual JSON array deserialization."""
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows updater')
def test_json_update_array_reaches_https_fetch(tmp_path):
    harness = tmp_path / 'Probe.cs'
    harness.write_text('''using System;class Probe {static int Main(string[] args){try{JarvisUpdateChecker.CheckAsync(args[0]).GetAwaiter().GetResult();return 0;}catch(Exception e){Console.WriteLine(e.InnerException==null?e.Message:e.InnerException.Message);return 1;}}}''')
    exe = tmp_path / 'Probe.exe'
    source = Path(__file__).parents[2] / 'deploy/yourjarvis/launcher/UpdateChecker.cs'
    subprocess.run([r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe', '/nologo', '/target:exe', f'/out:{exe}', '/reference:System.Net.Http.dll', '/reference:System.Web.Extensions.dll', str(harness), str(source)], check=True, capture_output=True)
    (tmp_path / 'app-version.json').write_text(json.dumps({'version':'0.1.5', 'manifestUrls':['https://127.0.0.1:1/update.json']}))
    result = subprocess.run([str(exe),str(tmp_path)],capture_output=True,timeout=20)
    # The unavailable HTTPS endpoint fails at the network layer, not URL parsing.
    assert result.returncode == 1
    assert 'HTTPS'.encode() not in result.stdout
