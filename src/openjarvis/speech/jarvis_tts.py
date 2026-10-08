"""Piper English plus local, cross-language JARVIS high Mandarin voice."""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from urllib.parse import urlsplit

from openjarvis.core.paths import get_resource_dir
from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.jarvis_runtime import voice_runtime
from openjarvis.speech.piper_tts import _CHINESE, PiperTTSBackend
from openjarvis.speech.tts import TTSBackend, TTSResult

_WORKER_LOCK = threading.Lock()
_WORKER_ID = "jarvis-high-qwen-local-v1"


def _worker_identity() -> str:
    instance = os.environ.get("JARVIS_VOICE_INSTANCE", "").strip()
    return f"{_WORKER_ID}:{instance}" if instance else _WORKER_ID


@TTSRegistry.register("jarvis")
class JarvisTTSBackend(TTSBackend):
    """Use a single advertised timbre, accepting legacy GUI voice settings."""

    backend_id = "jarvis"

    def __init__(self) -> None:
        self.root = get_resource_dir()
        self.python, self.engine, self.device = voice_runtime(self.root)
        self.worker_script = self.root / "scripts/qwen_tts_server.py"
        self.url = os.environ.get("JARVIS_VOICE_URL", "http://127.0.0.1:3337")
        self.worker_identity = _worker_identity()
        self.english = PiperTTSBackend()
        self._process = None

    def _ready(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=2) as response:
                data = json.load(response)
            if data.get("identity") != self.worker_identity:
                raise RuntimeError(
                    f"Voice address {self.url} is occupied by another service"
                )
            return bool(data.get("ready"))
        except (urllib.error.URLError, TimeoutError):
            return False

    def _ensure_worker(self) -> None:
        with _WORKER_LOCK:
            if self._ready():
                return
            if not self.python.is_file() or not self.worker_script.is_file():
                raise RuntimeError("The local JARVIS Mandarin runtime is missing")
            log_dir = self.root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment["HF_HUB_OFFLINE"] = "1"
            environment["PYTHONUNBUFFERED"] = "1"
            # Independent runtime prevents torch/transformers dependencies from
            # changing the assistant's STT and language-model environment.
            with (log_dir / "qwen-tts-worker.log").open("ab") as log:
                self._process = subprocess.Popen(
                    [
                        str(self.python),
                        str(self.worker_script),
                        "--engine",
                        self.engine,
                        "--device",
                        self.device,
                        "--port",
                        str(urlsplit(self.url).port or 3337),
                        "--identity",
                        self.worker_identity,
                    ],
                    cwd=str(self.root),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self._ready():
                    return
                if self._process.poll() not in (None, 0):
                    raise RuntimeError(
                        "JARVIS Mandarin worker failed; see logs/qwen-tts-worker.log"
                    )
                time.sleep(0.5)
            raise RuntimeError(
                "JARVIS Mandarin worker did not become ready within 180 seconds"
            )

    def health(self) -> bool:
        model = self.root / "models/speech/qwen3-tts-0.6b-base"
        reference = self.root / "models/piper/jarvis-high"
        if (
            not all(
                path.is_file()
                for path in (
                    self.python,
                    self.worker_script,
                    model / "model.safetensors",
                    model / "speech_tokenizer/model.safetensors",
                    reference / "reference.wav",
                    reference / "reference.txt",
                )
            )
            or not self.english.health()
        ):
            return False
        try:
            self._ensure_worker()
            return True
        except Exception:
            return False

    def warmup(self) -> bool:
        """Prime the Mandarin model so the next spoken reply can start promptly."""
        self._ensure_worker()
        request = urllib.request.Request(
            self.url + "/warmup",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
        if not data.get("loaded"):
            raise RuntimeError("JARVIS Mandarin voice could not be warmed")
        return True

    def available_voices(self) -> list[str]:
        return ["jarvis-high"]

    def supports_streaming(self) -> bool:
        self._ensure_worker()
        with urllib.request.urlopen(self.url + "/health", timeout=2) as response:
            return bool(json.load(response).get("streaming"))

    def synthesize_stream(
        self, text: str, *, voice_id="jarvis-high", speed=1.0, output_format="wav"
    ):
        """Yield mono, signed 16-bit little-endian PCM plus its sampling rate."""
        self._validate(text, voice_id, speed, output_format)
        if not _CHINESE.search(text):
            result = self.english.synthesize(text, voice_id="jarvis-high", speed=speed)
            with wave.open(io.BytesIO(result.audio)) as stream:
                yield stream.readframes(stream.getnframes()), stream.getframerate()
            return
        self._ensure_worker()
        request = urllib.request.Request(
            self.url + "/stream",
            data=json.dumps({"text": text, "speed": speed}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            rate = int(response.headers.get("X-Sample-Rate", "24000"))
            if response.headers.get("X-Voice-Id") != "jarvis-high" or rate != 24000:
                raise RuntimeError(
                    "Streaming worker returned an unexpected voice or format"
                )
            while chunk := response.read(4096):
                if len(chunk) % 2:
                    raise RuntimeError("Incomplete PCM sample from streaming worker")
                yield chunk, rate

    @staticmethod
    def _validate(text, voice_id, speed, output_format):
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("Speech speed must be between 0.5 and 2.0")
        if output_format != "wav":
            raise ValueError("JARVIS supports WAV output only")
        if (
            voice_id
            and voice_id != "jarvis-high"
            and not voice_id.startswith(("zf_", "zm_"))
        ):
            raise ValueError(f"Unknown JARVIS voice: {voice_id}")
        if not text.strip():
            raise ValueError("Speech text is empty")

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "jarvis-high",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        self._validate(text, voice_id, speed, output_format)
        if not _CHINESE.search(text):
            return self.english.synthesize(text, voice_id="jarvis-high", speed=speed)
        self._ensure_worker()
        request = urllib.request.Request(
            self.url + "/synthesize",
            data=json.dumps({"text": text, "speed": speed}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            audio = response.read()
        with wave.open(io.BytesIO(audio), "rb") as stream:
            rate = stream.getframerate()
            duration = stream.getnframes() / rate
        return TTSResult(
            audio=audio,
            format="wav",
            voice_id="jarvis-high",
            sample_rate=rate,
            duration_seconds=duration,
            metadata={
                "backend": "jarvis",
                "language": "zh",
                "synthesis": "qwen3-tts-cross-language-clone",
            },
        )

    def close(self) -> None:
        # The worker is shared by API, native voice and CLI sessions. Keep its
        # warm model alive; shutting down one client must not disrupt another.
        self.english.close()
