"""Loopback-only test gateway; invite store is isolated from real users."""
import argparse
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--store", type=Path, required=True)
args = parser.parse_args()
os.environ["OPENJARVIS_HOME"] = str(args.store.resolve())
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
sys.path.insert(0, str(args.root.resolve() / "src/src"))
import uvicorn
from openjarvis.engine.ollama import OllamaEngine
from openjarvis.server.friends import create_friends_app, invite_member

args.store.mkdir(parents=True, exist_ok=True)
members = args.store / "members.json"
if not members.exists():
    token = invite_member(members, "smoke-client")
    (args.store / "token.txt").write_text(token, encoding="utf-8")
app = create_friends_app(
    OllamaEngine(host="http://127.0.0.1:11434", num_gpu=0),
    model="qwen2.5:0.5b", members_path=members,
)
uvicorn.run(app, host="127.0.0.1", port=8003, access_log=False)
