"""Explicit, resumable speech downloads into the recipient's own data root."""

from __future__ import annotations

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--english", action="store_true")
    args = parser.parse_args()
    from huggingface_hub import hf_hub_download, snapshot_download

    speech = args.root / "models/speech"
    sensevoice = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    for name in ("model.int8.onnx", "tokens.txt", "LICENSE", "README.md"):
        hf_hub_download(sensevoice, name, local_dir=speech / "sensevoice")
    # Preserve the upstream card and license alongside the selected voices.
    snapshot_download(
        "hexgrad/Kokoro-82M",
        allow_patterns=[
            "config.json",
            "kokoro-v1_0.pth",
            "LICENSE*",
            "README.md",
            "VOICES.md",
            "voices/zm_yunjian.pt",
            "voices/zf_xiaoxiao.pt",
            "voices/bm_george.pt",
        ],
    )
    if args.english:
        snapshot_download(
            "Systran/faster-whisper-small.en", local_dir=speech / "whisper-small.en"
        )
    print("Speech model downloads complete.")


if __name__ == "__main__":
    main()
