"""First-run configuration, without installing or silently choosing a provider."""

from __future__ import annotations

import json

import click

from openjarvis.core.deployment import MODEL_PRESETS, VOICE_PRESETS, write_configuration
from openjarvis.core.paths import get_config_dir


@click.group()
def setup():
    """Reusable presets and first-run model/voice configuration."""


@setup.command("presets")
def presets():
    """List presets and estimated hardware requirements (JSON)."""
    click.echo(
        json.dumps(
            {
                "models": MODEL_PRESETS,
                "voices": VOICE_PRESETS,
                "hardware_note": "硬件建议为估算，非最低配置保证；语音另需内存。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@setup.command("configure")
@click.option("--profile", type=click.Choice(list(MODEL_PRESETS)), default="lite")
@click.option(
    "--model", default="", help="Full model ID; required for API/custom-local."
)
@click.option(
    "--base-url", default="", help="OpenAI-compatible URL (with or without /v1)."
)
@click.option("--api-key-env", default="JARVIS_LLM_API_KEY")
@click.option(
    "--prompt-api-key", is_flag=True, help="Read a key without echo; store separately."
)
@click.option("--voice", type=click.Choice(list(VOICE_PRESETS)), default="zh")
@click.option("--replace", is_flag=True, help="Back up and replace an existing config.")
def configure(profile, model, base_url, api_key_env, prompt_api_key, voice, replace):
    """Save a preset. No downloads or paid requests are made."""
    if prompt_api_key and (profile != "api" or api_key_env != "JARVIS_LLM_API_KEY"):
        raise click.ClickException(
            "--prompt-api-key requires API profile and the default key variable."
        )
    root = get_config_dir()
    # Validate everything before prompting or writing secrets.
    from openjarvis.core.deployment import configuration_text

    try:
        configuration_text(
            root,
            profile=profile,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            voice=voice,
        )
        if (root / "config.toml").exists() and not replace:
            raise FileExistsError(
                "Configuration exists. Pass --replace to back it up first."
            )
        key = click.prompt("API key", hide_input=True) if prompt_api_key else ""
        if key:
            from openjarvis.core.credentials import save_credential

            save_credential("llm", "JARVIS_LLM_API_KEY", key)
        path = write_configuration(
            root,
            replace=replace,
            profile=profile,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            voice=voice,
        )
    except (ValueError, FileExistsError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Saved {path}. Restart JARVIS to use this configuration.")
    if profile in {"lite", "balanced"}:
        click.echo(
            f"Install model: ollama pull {model or MODEL_PRESETS[profile]['model']}"
        )
    click.echo("Run jarvis setup check to inspect missing speech/model assets.")


@setup.command("wizard")
@click.pass_context
def wizard(ctx):
    """Interactive first-run wizard, suitable for a .cmd launcher."""
    click.echo("JARVIS 首次配置：模型与语音分开设置，API 密钥由你提供。")
    for name, preset in MODEL_PRESETS.items():
        click.echo(f"  {name}: {preset['description']}")
    profile = click.prompt(
        "模型方案", type=click.Choice(list(MODEL_PRESETS)), default="lite"
    )
    model = click.prompt("模型 ID") if profile in {"api", "custom-local"} else ""
    base_url = click.prompt("API 地址（含 /v1 亦可）") if profile == "api" else ""
    key = profile == "api" and click.confirm(
        "保存 API 密钥？本地无密钥服务选 No", default=False
    )
    for name, preset in VOICE_PRESETS.items():
        click.echo(f"  {name}: {preset['description']}")
    voice = click.prompt(
        "语音方案", type=click.Choice(list(VOICE_PRESETS)), default="zh"
    )
    replace = (get_config_dir() / "config.toml").exists()
    if replace and not click.confirm(
        "已有配置。备份后替换模型、语音和初始行为设置？", default=False
    ):
        return
    ctx.invoke(
        configure,
        profile=profile,
        model=model,
        base_url=base_url,
        api_key_env="JARVIS_LLM_API_KEY",
        prompt_api_key=key,
        voice=voice,
        replace=replace,
    )


@setup.command("runtime")
def runtime():
    """Machine-readable launch choice; never returns credentials."""
    from openjarvis.core.config import load_config

    cfg = load_config()
    click.echo(
        json.dumps(
            {
                "engine": cfg.engine.default,
                "agent": cfg.agent.default_agent,
                "model": cfg.intelligence.default_model,
            }
        )
    )


@setup.command("check")
def check():
    """Inspect local hardware/assets; no model downloads or API requests."""
    from openjarvis.core.config import load_config

    cfg = load_config()
    root = get_config_dir()
    speech = {
        "sensevoice": all(
            (root / "models/speech/sensevoice" / n).is_file()
            for n in ("model.int8.onnx", "tokens.txt")
        ),
        "whisper_english": (
            root / "models/speech/whisper-small.en/model.bin"
        ).is_file(),
    }
    click.echo(
        json.dumps(
            {
                "root": str(root),
                "engine": cfg.engine.default,
                "model": cfg.intelligence.default_model,
                "ram_gb": cfg.hardware.ram_gb,
                "cpu_count": cfg.hardware.cpu_count,
                "speech_assets": speech,
                "note": "Missing voice assets do not prevent text chat.",
            },
            indent=2,
        )
    )
