"""Exercise the selected neural voice before declaring installation complete."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--voice", required=True)
    args = parser.parse_args()
    args.root = args.root.resolve()
    os.chdir(args.root)
    import numpy as np
    import sherpa_onnx
    from kokoro import KPipeline

    speech = args.root / "models/speech"
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(speech / "sensevoice/model.int8.onnx"),
        tokens=str(speech / "sensevoice/tokens.txt"),
        num_threads=2,
        use_itn=True,
        debug=False,
    )
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
    recognizer.decode_stream(stream)
    english = args.voice == "en"
    if english:
        from faster_whisper import WhisperModel

        from openjarvis.speech._espeak_windows import prepare_espeak_windows

        prepare_espeak_windows()
        WhisperModel(
            str(speech / "whisper-small.en"),
            device="cpu",
            compute_type="int8",
            local_files_only=True,
        )
    voice = (
        "bm_george"
        if english
        else "zf_xiaoxiao"
        if args.voice == "zh-female"
        else "zm_yunjian"
    )
    pipeline = KPipeline(
        lang_code="b" if english else "z", repo_id="hexgrad/Kokoro-82M", device="cpu"
    )
    result = list(pipeline("Hello." if english else "安装检查通过。", voice=voice))
    if not result or not any(item[2] is not None and len(item[2]) for item in result):
        raise RuntimeError("语音合成没有产生音频。")
    print("Speech recognition and synthesis passed (offline).")


if __name__ == "__main__":
    main()
