"""User reference voices on the shared Qwen model; explicit output language."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import urllib.request
import wave
from pathlib import Path

from openjarvis.core.paths import get_resource_dir
from openjarvis.speech.jarvis_runtime import voice_runtime
from openjarvis.speech.jarvis_tts import JarvisTTSBackend, _worker_identity
from openjarvis.speech.tts import TTSResult


class QwenReferenceTTSBackend(JarvisTTSBackend):
    backend_id = "qwen-reference"

    def __init__(self, profile):
        # Reuse worker lifecycle, without requiring or routing through Piper.
        self.root = get_resource_dir()
        self.python, self.engine, self.device = voice_runtime(self.root)
        self.worker_script = self.root / "scripts/qwen_tts_server.py"
        self.url = os.environ.get("JARVIS_VOICE_URL", "http://127.0.0.1:3337")
        self.worker_identity = _worker_identity()
        self._process = None
        self.voice_id = profile["voice_id"]
        path = Path(profile["_pack_root"])
        self.reference_audio = base64.b64encode(
            (path / "reference.wav").read_bytes()
        ).decode("ascii")
        self.reference_text = (path / "reference.txt").read_text(encoding="utf-8")
        self.embedding_only = profile.get("_embedding_only", False)

    def health(self):
        return (
            self.python.is_file()
            and self.worker_script.is_file()
            and all(
                (self.root / file).is_file()
                for file in (
                    "models/speech/qwen3-tts-0.6b-base/model.safetensors",
                    "models/speech/qwen3-tts-0.6b-base/speech_tokenizer/model.safetensors",
                )
            )
        )

    def available_voices(self):
        return [self.voice_id]

    def _payload(self, text, voice_id, speed, output_format, language):
        if voice_id != self.voice_id:
            raise ValueError("Unknown reference voice")
        if language not in {"zh", "en"}:
            raise ValueError("Output language must be zh or en")
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("Speech speed must be between 0.5 and 2.0")
        if output_format != "wav" or not text.strip():
            raise ValueError("Reference voices require nonempty text and WAV output")
        self._ensure_worker()
        with urllib.request.urlopen(self.url + "/health", timeout=2) as response:
            health = json.load(response)
            if health.get("reference_api") != 1 or (self.embedding_only and health.get("embedding_only_api") != 1):
                raise RuntimeError("语音服务需要重启以启用自定义音色")
        return {
            "text": text,
            "speed": speed,
            "voice_id": voice_id,
            "language": "Chinese" if language == "zh" else "English",
            "reference_audio": self.reference_audio,
            "reference_text": self.reference_text,
            "embedding_only": self.embedding_only,
        }

    def _request(self, endpoint, payload):
        return urllib.request.Request(
            self.url + endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def synthesize(
        self, text, *, voice_id, speed=1.0, output_format="wav", language="zh"
    ):
        payload = self._payload(text, voice_id, speed, output_format, language)
        with urllib.request.urlopen(
            self._request("/synthesize", payload), timeout=600
        ) as response:
            if response.headers.get("X-Voice-Id") != self.voice_id:
                raise RuntimeError("Worker returned a different reference voice")
            audio = response.read()
        with wave.open(io.BytesIO(audio), "rb") as stream:
            rate = stream.getframerate()
            duration = stream.getnframes() / rate
        return TTSResult(
            audio=audio,
            format="wav",
            voice_id=self.voice_id,
            sample_rate=rate,
            duration_seconds=duration,
            metadata={"backend": self.backend_id, "language": language},
        )

    def synthesize_stream(
        self, text, *, voice_id, speed=1.0, output_format="wav", language="zh"
    ):
        payload = self._payload(text, voice_id, speed, output_format, language)
        with urllib.request.urlopen(
            self._request("/stream", payload), timeout=600
        ) as response:
            rate = int(response.headers.get("X-Sample-Rate", "0"))
            if response.headers.get("X-Voice-Id") != self.voice_id or rate != 24000:
                raise RuntimeError(
                    "Worker returned an unexpected reference voice or format"
                )
            while chunk := response.read(4096):
                if len(chunk) % 2:
                    raise RuntimeError("Incomplete PCM sample")
                yield chunk, rate

    def close(self):
        pass  # Worker belongs to all local clients.
