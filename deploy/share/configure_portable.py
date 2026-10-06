"""Write a portable JARVIS configuration from installer arguments."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import tomllib

from openjarvis.core.credentials import delete_credential, save_credential
from openjarvis.core.deployment import MODEL_PRESETS, VOICE_PRESETS, write_configuration


def validate_request(data: dict) -> dict:
    profile, voice = data.get("profile", "lite"), data.get("voice", "text")
    if profile not in MODEL_PRESETS or voice not in VOICE_PRESETS:
        raise ValueError("请选择有效的模型和语音方案。")
    model = data.get("model", "").strip()
    if not model or len(model) > 256 or any(ord(c) < 32 for c in model):
        raise ValueError("请填写有效的模型名称（最多 256 个字符）。")
    if profile not in {"api", "remote-host"} and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model
    ):
        raise ValueError("本地模型名称包含无效字符。")
    address = data.get("url", "").strip().rstrip("/")
    if profile in {"api", "remote-host"}:
        parsed = urlsplit(address)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请填写完整的 http/https API 地址，密钥应填在密钥栏。")
        _ = parsed.port
    return {**data, "profile": profile, "voice": voice, "model": model, "url": address}


def existing_request(root: Path) -> dict:
    with (root / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    engine = config.get("engine", {}).get("default", "ollama")
    if engine not in {"ollama", "api"}:
        raise ValueError("当前推理引擎不受修复向导支持，请取消保留配置并重新选择方案。")
    if (
        engine == "ollama"
        and config.get("engine", {})
        .get("ollama", {})
        .get("host", "http://127.0.0.1:11434")
        .split(":")[:2]
        != ["http", "//127.0.0.1"]
    ):
        raise ValueError(
            "修复向导只管理本机 Ollama，请重新选择兼容 API 以连接远程服务。"
        )
    return validate_request(
        {
            "profile": "api" if engine == "api" else "custom-local",
            "voice": config.get("deployment", {}).get("voice", "text"),
            "model": config.get("intelligence", {}).get("default_model", ""),
            "url": config.get("engine", {}).get("api", {}).get("host", ""),
            "preserve": True,
        }
    )


def check_request(root: Path, data: dict) -> None:
    import httpx

    data = validate_request(data)
    if data["profile"] in {"api", "remote-host"}:
        key = data.get("key", "").strip()
        if data.get("preserve"):
            from openjarvis.core.config import load_config
            from openjarvis.core.credentials import load_credentials

            credentials = load_credentials(path=root / "credentials.toml")
            config = load_config(root / "config.toml")
            key = os.environ.get(config.engine.api.api_key_env, "")
            key = credentials.get("llm", {}).get(
                config.engine.api.api_key_env, key
            )
        base = data["url"]
        endpoint = base + (
            "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
        )
        headers = {"Authorization": "Bearer " + key} if key else {}
        try:
            response = httpx.post(
                endpoint,
                headers=headers,
                json={
                    "model": data["model"],
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                timeout=90,
            )
            if response.status_code >= 400:
                raise ValueError(
                    f"API 连接检查失败（HTTP {response.status_code}）。"
                    "请检查地址、模型名称、密钥和账户额度。"
                )
            if not response.json().get("choices"):
                raise ValueError("服务没有返回兼容的聊天结果，请使用 OpenAI 兼容 API。")
        except httpx.HTTPError:
            raise ValueError("无法连接 API，请检查网络和服务地址后重试。") from None
    else:
        try:
            response = httpx.post(
                os.environ.get("JARVIS_LOCAL_OLLAMA", "http://127.0.0.1:11434") + "/api/generate",
                json={
                    "model": data["model"],
                    "prompt": "Hi",
                    "stream": False,
                    "options": {"num_predict": 1, "num_ctx": 2048},
                },
                timeout=180,
                trust_env=False,
            )
            response.raise_for_status()
            if "response" not in response.json():
                raise ValueError("本地模型没有返回有效结果。")
        except httpx.HTTPError:
            raise ValueError(
                "本地模型启动失败，请检查内存和模型下载情况后重试。"
            ) from None
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401

    from openjarvis.server.app import create_app  # noqa: F401


def run_action(root: Path, action: str, data: dict) -> None:
    data = validate_request(data)
    if action == "check":
        check_request(root, data)
        static = root / "src/src/openjarvis/server/static/index.html"
        if not static.is_file():
            raise ValueError("网页界面文件缺失，请重新解压完整安装包。")
    elif action == "write" and not data.get("preserve"):
        write_configuration(
            root,
            replace=(root / "config.toml").exists(),
            profile=data["profile"],
            model=data["model"],
            base_url=data["url"],
            api_key_env="JARVIS_LLM_API_KEY",
            voice=data["voice"],
        )
        if data["profile"] in {"api", "remote-host"}:
            key = data.get("key", "").strip()
            if key:
                save_credential(
                    "llm", "JARVIS_LLM_API_KEY", key, path=root / "credentials.toml"
                )
            else:
                delete_credential(
                    "llm", "JARVIS_LLM_API_KEY", path=root / "credentials.toml"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--action", choices=["existing", "validate", "write", "check"])
    parser.add_argument("--profile", choices=MODEL_PRESETS, default="lite")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--voice", choices=VOICE_PRESETS, default="text")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    if args.action:
        try:
            if args.action == "existing":
                print(json.dumps(existing_request(args.root), ensure_ascii=False))
            else:
                run_action(args.root, args.action, json.load(sys.stdin))
                print("检查通过")
        except Exception as exc:
            # Avoid tracebacks containing request bodies or credentials.
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        return
    if args.profile in {"api", "remote-host"} and not args.base_url.strip():
        raise ValueError("API 或远程主机配置必须填写服务地址。")
    write_configuration(
        args.root,
        replace=(args.root / "config.toml").exists(),
        profile=args.profile,
        model=args.model,
        base_url=args.base_url,
        api_key_env="JARVIS_LLM_API_KEY",
        voice=args.voice,
    )
    api_key = args.api_key or __import__("os").environ.get("JARVIS_INSTALL_API_KEY", "")
    if api_key.strip():
        save_credential(
            "llm",
            "JARVIS_LLM_API_KEY",
            api_key,
            path=args.root / "credentials.toml",
        )
    print("configuration-ready")


if __name__ == "__main__":
    main()
