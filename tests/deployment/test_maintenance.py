"""Exercise actual native removal on disposable installations only."""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows maintenance')


@pytest.fixture(scope='module')
def maintenance(tmp_path_factory):
    folder = tmp_path_factory.mktemp('maintenance')
    harness = folder / 'Test.cs'
    harness.write_text('''using System; class Test {static int Main(string[] args) {try {MaintenanceProgram.Uninstall(args[0], args[1]=="all", Console.WriteLine).GetAwaiter().GetResult();return 0;}catch(Exception e){Console.WriteLine(e.Message);return 1;}}}''')
    exe = folder / 'Test.exe'
    subprocess.run([r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe', '/nologo', '/target:exe', '/main:Test', f'/out:{exe}', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll', str(harness), str(Path(__file__).parents[2] / 'deploy/yourjarvis/launcher/Maintenance.cs')], check=True, capture_output=True)
    return exe


def installation(root):
    root.mkdir()
    files = ['JARVIS.exe', 'JARVIS-Uninstall.exe', 'app-version.json', 'src/app.py']
    for file in files:
        path = root / file
        path.parent.mkdir(exist_ok=True)
        path.write_text('program')
    (root / 'package-manifest.json').write_text(json.dumps({'files': [{'path': f} for f in files]}))
    for directory in ('data', 'models', 'cache', 'logs'):
        (root / directory).mkdir()
        (root / directory / 'fixture').write_text(directory)
    (root / 'config.toml').write_text('personal')
    (root / 'credentials.toml').write_text('private')
    (root / 'my-document.txt').write_text('unknown')


@pytest.mark.parametrize('mode', ['keep', 'all'])
def test_remove_preserves_only_requested_state(maintenance, tmp_path, mode):
    root = tmp_path / '含 空格的安装目录'
    installation(root)
    result = subprocess.run([str(maintenance), str(root), mode], capture_output=True)
    assert result.returncode == 0, result.stdout
    assert not (root / 'JARVIS.exe').exists()
    assert not (root / 'src').exists()
    assert not (root / 'models').exists()
    assert not (root / 'cache').exists()
    assert (root / 'my-document.txt').read_text() == 'unknown'
    for file in ('data/fixture', 'config.toml', 'credentials.toml', 'logs/fixture'):
        assert (root / file).exists() == (mode == 'keep')


def test_escape_manifest_refuses_before_any_deletion(maintenance, tmp_path):
    root = tmp_path / 'app'
    installation(root)
    (root / 'package-manifest.json').write_text(json.dumps({'files': [{'path': 'JARVIS.exe'}, {'path': '../other'}]}))
    assert subprocess.run([str(maintenance), str(root), 'all'], capture_output=True).returncode != 0
    assert (root / 'JARVIS.exe').exists()
    assert (root / 'config.toml').exists()


def test_development_checkout_is_not_uninstalled(maintenance, tmp_path):
    root = tmp_path / 'dev'
    installation(root)
    (root / 'src/.git').mkdir()
    assert subprocess.run([str(maintenance), str(root), 'all'], capture_output=True).returncode != 0
    assert (root / 'JARVIS.exe').exists()
