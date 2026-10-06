"""Developer QA only: isolated state, temporary invitations, loopback binds."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=["friends", "settings"], required=True)
    parser.add_argument("--port", type=int, default=8003)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    os.environ["OPENJARVIS_HOME"] = str(args.root)
    os.environ["OPENJARVIS_NO_UPDATE_CHECK"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"

    import uvicorn

    from openjarvis.core.config import load_config
    from openjarvis.core.deployment import write_configuration
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.server.friends import create_friends_app, invite_member

    if not (args.root / "config.toml").exists():
        write_configuration(args.root, voice="text")
    engine = OllamaEngine(host="http://127.0.0.1:11434", num_ctx=2048, num_gpu=0)
    if args.mode == "friends":
        token = invite_member(args.root / "friends-members.json", "QA user")
        (args.root / "qa-token.txt").write_text(token, encoding="utf-8")
        app = create_friends_app(
            engine,
            model="qwen2.5:0.5b",
            members_path=args.root / "friends-members.json",
            num_ctx=2048,
        )
    else:
        from openjarvis.server.app import create_app

        cfg = load_config()
        app = create_app(engine, "qwen2.5:0.5b", config=cfg, engine_name="ollama")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
