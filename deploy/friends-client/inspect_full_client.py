"""Manual integration QA against this client's native WebView only."""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--restart", action="store_true")
parser.add_argument("--local", action="store_true")
parser.add_argument("--debug-state", action="store_true")
parser.add_argument("--remote", type=Path)
args = parser.parse_args()
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9248")
    page = browser.contexts[0].pages[0]
    if args.debug_state:
        print("STATE=" + json.dumps(page.evaluate("({settings:localStorage.getItem('openjarvis-settings'),input:document.querySelector('textarea')?.value,placeholder:document.querySelector('textarea')?.placeholder,inert:document.querySelector('textarea')?.parentElement.inert,active:document.activeElement?.tagName,buttons:[...document.querySelectorAll('button')].map(b=>({title:b.title,disabled:b.disabled}))})"), ensure_ascii=False))
        print("MODELS=" + json.dumps(page.evaluate("fetch('/v1/models').then(r=>r.json())"), ensure_ascii=False))
    if args.restart:
        page.evaluate("window.chrome.webview.postMessage({type:'restart-backend'})")
        time.sleep(3)
        page.wait_for_function("!!document.querySelector('textarea')", timeout=120000)
    print(json.dumps({"url": page.url, "desktop": page.evaluate("!!window.__JARVIS_DESKTOP__"),
                      "body": page.locator("body").inner_text()[:6000],
                      "links": page.locator("a").evaluate_all("nodes => nodes.map(n=>({text:n.innerText,href:n.getAttribute('href')}))")}, ensure_ascii=False))
    if args.local:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.evaluate("const s=JSON.parse(localStorage.getItem('openjarvis-settings'));s.speechEnabled=false;s.wakeWordEnabled=false;localStorage.setItem('openjarvis-settings',JSON.stringify(s))")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("!!document.querySelector('textarea') && document.querySelector('textarea').placeholder.includes('给') && !document.querySelector('textarea').disabled", timeout=60000)
        page.locator("textarea").fill("你好，请用一句话介绍自己。")
        page.locator("textarea").press("Enter")
        page.wait_for_function("document.body.innerText.includes('你好，请用一句话介绍自己。')", timeout=20000)
        page.wait_for_timeout(2000)
        page.wait_for_function("!document.querySelector('button[aria-label=\"停止生成\"]') && document.querySelector('textarea') && !document.querySelector('textarea').disabled", timeout=120000)
        print("CHAT=" + page.locator("body").inner_text()[:3500])
        page.screenshot(path=str(args.root / "full-client-local-chat.png"))
        page.get_by_role("button", name="设置", exact=True).click()
        page.get_by_role("heading", name="模型与首次配置预设").wait_for(timeout=30000)
        assert page.get_by_role("option", name="连接 JARVIS 远程主机").count() == 1
        assert page.get_by_role("button", name="应用并重启模型服务").count() == 1
        page.screenshot(path=str(args.root / "full-client-settings.png"), full_page=True)
        print("SETTINGS=" + page.locator("body").inner_text()[:6000])
        assert not errors, errors
    if args.remote:
        page.get_by_role("button", name="设置", exact=True).click()
        heading = page.get_by_role("heading", name="模型与首次配置预设")
        heading.wait_for(timeout=30000)
        section = page.locator("section").filter(has=heading)
        section.locator("select").select_option("remote-host")
        section.locator("input[type=url]").fill("http://127.0.0.1:8003/v1")
        section.locator("input[type=password]").fill((args.remote / "token.txt").read_text().strip())
        section.get_by_role("button", name="保存模型配置", exact=True).click()
        section.get_by_role("status").wait_for(timeout=10000) if section.get_by_role("status").count() else page.wait_for_timeout(1000)
        section.get_by_role("button", name="应用并重启模型服务", exact=True).click()
        page.wait_for_timeout(2000)
        page.wait_for_function("document.querySelector('textarea') && document.querySelector('textarea').placeholder.includes('给')", timeout=120000)
        page.wait_for_timeout(1000)
        info = page.evaluate("fetch('/v1/info').then(r=>r.json())")
        assert info["engine"] == "api" and info["model"] == "host-model", info
        assert page.evaluate("fetch('/v1/memory/stats').then(r=>r.json())")["entries"] > 0
        page.locator("textarea").fill("你好，请用一句话介绍自己。")
        page.locator("textarea").press("Enter")
        page.wait_for_timeout(3000)
        page.wait_for_function("!document.querySelector('button[title=\"停止生成\"]') && !document.querySelector('button[title=\"Stop generating\"]')", timeout=120000)
        print("REMOTE=" + page.locator("body").inner_text()[:3500])
        assert "api -" in page.locator("body").inner_text()
        page.screenshot(path=str(args.root / "full-client-remote-chat.png"))
    page.screenshot(path=str(args.root / "full-client-home.png"))
    browser.close()
