"""Independent local recognizers selected by the user's spoken language."""

from __future__ import annotations

import io
import re
import threading
from pathlib import Path

from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult
from openjarvis.speech.faster_whisper import FasterWhisperBackend
from openjarvis.speech.text import normalize_transcript


class SenseVoiceBackend(SpeechBackend):
    """Mandarin profile: SenseVoiceSmall quantized ONNX, explicitly zh."""

    backend_id = "sensevoice"

    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self._recognizer = None
        self._last_error = ""

    def _ensure_model(self):
        if self._recognizer is None:
            import sherpa_onnx

            model = self.model_dir / "model.int8.onnx"
            tokens = self.model_dir / "tokens.txt"
            if not model.is_file() or not tokens.is_file():
                raise RuntimeError(
                    f"Chinese speech model is missing in {self.model_dir}"
                )
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model),
                tokens=str(tokens),
                language="zh",
                use_itn=True,
                num_threads=4,
                provider="cpu",
                debug=False,
            )
        return self._recognizer

    def transcribe(self, audio: bytes, *, format="wav", language=None):
        from faster_whisper.audio import decode_audio

        recognizer = self._ensure_model()
        samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        text = re.sub(r"<\|[^|]*\|>", "", stream.result.text).strip()
        return TranscriptionResult(
            text=normalize_transcript(text, "zh"),
            language="zh",
            duration_seconds=len(samples) / 16000,
        )

    def health(self):
        try:
            self._ensure_model()
            self._last_error = ""
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def last_error(self):
        return self._last_error

    def supported_formats(self):
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]


@SpeechRegistry.register("language-routed")
class LanguageRoutedSpeechBackend(SpeechBackend):
    """Do not use the conversation LLM to transcribe, translate, or correct audio.

    Language selection picks an actual separate recognizer. A lock prevents
    microphone and uploaded dictation from concurrently entering native ASR.
    """

    backend_id = "language-routed"

    def __init__(self, chinese_model="", english_model="small.en", language="zh"):
        self.default_language = language or "zh"
        self.chinese = SenseVoiceBackend(
            chinese_model or str(get_config_dir() / "models" / "speech" / "sensevoice")
        )
        self.english = FasterWhisperBackend(
            model_size=english_model, device="cpu", compute_type="int8"
        )
        self._lock = threading.Lock()
        self._last_error = ""

    def _select(self, language):
        key = (
            (language or self.default_language).lower().replace("_", "-").split("-")[0]
        )
        if key not in {"zh", "en"}:
            raise ValueError(
                "Recognition language must be Simplified Chinese or English"
            )
        return key, self.chinese if key == "zh" else self.english

    def transcribe(self, audio: bytes, *, format="wav", language=None):
        try:
            key, backend = self._select(language)
            with self._lock:
                result = backend.transcribe(audio, format=format, language=key)
            self._last_error = ""
            return result
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def health(self):
        _, backend = self._select(None)
        with self._lock:
            healthy = backend.health()
        self._last_error = backend.last_error() or "" if not healthy else ""
        return healthy

    def profiles(self):
        chinese = self.chinese.model_dir
        english = Path(self.english._model_size)
        return {
            "zh": {
                "model": "SenseVoiceSmall INT8",
                "language": "zh",
                "available": (chinese / "model.int8.onnx").is_file()
                and (chinese / "tokens.txt").is_file(),
            },
            "en": {
                "model": "Whisper small.en INT8",
                "language": "en",
                "available": (english / "model.bin").is_file(),
            },
        }

    def last_error(self):
        return self._last_error

    def supported_formats(self):
        return self.chinese.supported_formats()
