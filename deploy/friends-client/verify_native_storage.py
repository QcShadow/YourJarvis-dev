"""Check that a new loopback port does not lose full-client browser state."""
import argparse
import json
import socket
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9248")
    page = browser.contexts[0].pages[0]
    before = page.evaluate("Object.fromEntries(Object.keys(localStorage).map(k=>[k,localStorage.getItem(k)]))")
    port = int(page.url.split(":")[2].split("/")[0])
    try:
        page.evaluate("window.chrome.webview.postMessage({type:'quit'})")
        page.wait_for_timeout(2000)
    except Exception:
        pass
    with socket.socket() as reserved:
        # Wait for this client's backend to exit before reserving its old port.
        # Do not use SO_REUSEADDR to compete with a still-running listener.
        for _ in range(120):
            try:
                reserved.bind(("127.0.0.1", port))
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Client's old backend port did not close")
        reserved.listen()
        subprocess.Popen([str(root / "JARVIS-Link.exe"), "--hidden", "--debug"],
                         cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(240):
            try:
                new_browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9248")
                if new_browser.contexts[0].pages:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Native browser did not become ready")
        page = new_browser.contexts[0].pages[0]
        page.wait_for_function("localStorage.getItem('openjarvis-settings')", timeout=120000)
        after = page.evaluate("Object.fromEntries(Object.keys(localStorage).map(k=>[k,localStorage.getItem(k)]))")
        assert before["openjarvis-settings"] == after["openjarvis-settings"]
        assert before["openjarvis-conversations"] == after["openjarvis-conversations"]
        assert int(page.url.split(":")[2].split("/")[0]) != port
        print(json.dumps({"state_preserved": True, "old_port": port, "new_url": page.url}))
        try:
            page.evaluate("window.chrome.webview.postMessage({type:'quit'})")
        except Exception:
            pass
