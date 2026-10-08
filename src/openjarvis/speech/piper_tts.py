"""Local JARVIS English voice, with Kokoro for Mandarin utterances."""

from __future__ import annotations

import io
import math
import os
import re
import threading
import wave
from pathlib import Path
from typing import Any

from openjarvis.core.paths import get_resource_dir
from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_VOICE_ID = "jarvis-high"
_CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U000323af]")


@TTSRegistry.register("piper")
class PiperTTSBackend(TTSBackend):
    """Keep the Piper ONNX model warm on CPU; preserve Chinese voice settings."""

    backend_id = "piper"

    def __init__(
        self,
        model_path: str = "",
        chinese_voice_id: str = "zm_yunjian",
        strict_voice: bool = False,
        voice_id: str = _VOICE_ID,
        language: str = "en_GB",
        speaker_id: int | None = None,
    ) -> None:
        root = get_resource_dir()
        self.model_path = (
            Path(model_path)
            if model_path
            else (root / "models" / "piper" / _VOICE_ID / f"{_VOICE_ID}.onnx")
        )
        self.chinese_voice_id = chinese_voice_id
        self.strict_voice = strict_voice
        self.voice_id = voice_id
        self.language = language
        self.speaker_id = speaker_id
        self._voice: Any = None
        self._chinese_backend: Any = None
        self._lock = threading.RLock()

    def _load_voice(self):
        if self._voice is None:
            from piper import PiperVoice
            from piper.phonemize_espeak import ESPEAK_DATA_DIR

            # eSpeak's Windows file API cannot open Unicode installation paths.
            # The desktop starts in its own root; an ASCII relative data path
            # also prevents eSpeak from falling back to its build-machine path.
            data_path = str(ESPEAK_DATA_DIR)
            if os.name == "nt" and not data_path.isascii():
                data_path = os.path.relpath(data_path)
                if not data_path.isascii():
                    raise RuntimeError("请从安装目录启动 Piper 语音，或使用贾维斯桌面快捷方式。")
            self._voice = PiperVoice.load(
                str(self.model_path), use_cuda=False, espeak_data_dir=data_path
            )
        return self._voice

    def health(self) -> bool:
        if (
            not self.model_path.is_file()
            or not Path(str(self.model_path) + ".json").is_file()
        ):
            return False
        try:
            with self._lock:
                self._load_voice()
            return True
        except Exception:
            return False

    def available_voices(self) -> list[str]:
        return [self.voice_id]

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Speech speed must be finite and greater than zero")
        if output_format != "wav":
            raise ValueError("Piper supports WAV output only")
        with self._lock:
            if _CHINESE.search(text) and not self.strict_voice:
                from openjarvis.speech.kokoro_tts import KokoroTTSBackend

                if self._chinese_backend is None:
                    self._chinese_backend = KokoroTTSBackend()
                chinese_voice = (
                    voice_id
                    if voice_id.startswith(("zf_", "zm_"))
                    else self.chinese_voice_id
                )
                return self._chinese_backend.synthesize(
                    text, voice_id=chinese_voice, speed=speed, output_format="wav"
                )

            # The GUI sends its saved Chinese voice with every request. English
            # must still use JARVIS, rather than interpreting that ID in Piper.
            if (
                voice_id
                and voice_id != self.voice_id
                and (self.strict_voice or not voice_id.startswith(("zf_", "zm_")))
            ):
                raise ValueError(f"Unknown Piper voice: {voice_id}")
            from piper import SynthesisConfig

            voice = self._load_voice()
            output = io.BytesIO()
            with wave.open(output, "wb") as wav_file:
                voice.synthesize_wav(
                    text,
                    wav_file,
                    syn_config=SynthesisConfig(
                        length_scale=voice.config.length_scale / speed,
                        **(
                            {"speaker_id": self.speaker_id}
                            if self.speaker_id is not None
                            else {}
                        ),
                    ),
                )
            audio = output.getvalue()
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            rate = wav_file.getframerate()
            duration = wav_file.getnframes() / rate
        return TTSResult(
            audio=audio,
            format="wav",
            voice_id=self.voice_id,
            sample_rate=rate,
            duration_seconds=duration,
            metadata={"backend": "piper", "language": self.language},
        )

    def close(self) -> None:
        with self._lock:
            self._voice = None
            if self._chinese_backend is not None:
                self._chinese_backend.close()
                self._chinese_backend = None
