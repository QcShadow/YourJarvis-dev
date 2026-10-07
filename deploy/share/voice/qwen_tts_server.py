"""Local Mandarin reconstruction of the Piper JARVIS high voice.

Runs in an isolated environment, using CUDA when installed or otherwise CPU.
Use --preview for a one-shot audition, or no arguments for the loopback worker.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from qwen_voice_audio import adjust_audio, generation_instruction, pitch_semitones

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models/speech/qwen3-tts-0.6b-base"
REFERENCE_DIR = ROOT / "models/piper/jarvis-high"
IDENTITY = "jarvis-high-qwen-local-v1"


class VoicePool:
    """Keep the service online while releasing idle voice weights/graphs."""

    def __init__(self, voice=None, device="cuda:0", engine="faster"):
        self.voice = voice
        self.device = voice.device if voice is not None else device
        self.engine = voice.engine if voice is not None else engine
        self.lock = threading.Lock()
        self.suspended = threading.Event()
        self.last_used = time.monotonic()
        threading.Thread(target=self._idle_loop, daemon=True).start()

    def _release(self):
        import gc

        import torch

        self.voice = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def suspend(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            self.suspended.set()
            self._release()
            return True
        finally:
            self.lock.release()

    def resume(self):
        self.suspended.clear()

    def _image_lease_active(self):
        try:
            lease = json.loads(
                (ROOT / "data/gpu-image-lease.json").read_text(encoding="utf-8")
            )
            return lease.get("expires_at", 0) > time.time()
        except (OSError, ValueError):
            return False

    def _get_voice(self):
        if self.voice is None:
            self.voice = Voice(self.device, self.engine)
        return self.voice

    def _wait_available(self):
        while True:
            active = self._image_lease_active()
            if self.suspended.is_set() and not active:
                self.suspended.clear()
            if not self.suspended.is_set() and not active:
                return
            time.sleep(0.2)

    def synthesize(self, text, speed=1.0, **kwargs):
        while True:
            self._wait_available()
            with self.lock:
                if self.suspended.is_set() or self._image_lease_active():
                    continue
                try:
                    return self._get_voice().synthesize(text, speed, **kwargs)
                finally:
                    self.last_used = time.monotonic()

    def stream(self, text, speed=1.0, **kwargs):
        while True:
            self._wait_available()
            with self.lock:
                if self.suspended.is_set() or self._image_lease_active():
                    continue
                try:
                    yield from self._get_voice().stream(text, speed, **kwargs)
                finally:
                    self.last_used = time.monotonic()
                return

    def _idle_loop(self):
        while True:
            time.sleep(5)
            try:
                policy = json.loads(
                    (ROOT / "data/model-scheduler.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                policy = {}
            seconds = policy.get("voice_idle_seconds", 120)
            if time.monotonic() - self.last_used > seconds and self.lock.acquire(
                blocking=False
            ):
                try:
                    if self.voice is not None:
                        self._release()
                finally:
                    self.lock.release()


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    voice_id: str = Field(
        default="jarvis-high", pattern=r"^(jarvis-high|user-[0-9a-f]{32})$"
    )
    language: Literal["Chinese", "English"] = "Chinese"
    reference_audio: str = Field(default="", max_length=16 * 1024 * 1024)
    reference_text: str = Field(default="", max_length=3000)
    embedding_only: bool = False

    @model_validator(mode="after")
    def validate_reference(self):
        if self.voice_id == "jarvis-high":
            if self.reference_audio or self.reference_text:
                raise ValueError(
                    "Built-in voice cannot be replaced by reference assets"
                )
            return self
        if not self.embedding_only and not self.reference_text.strip():
            raise ValueError("Reference transcript is required")
        try:
            data = base64.b64decode(self.reference_audio, validate=True)
            with wave.open(io.BytesIO(data), "rb") as audio:
                rate = audio.getframerate()
                size = audio.getnframes() * audio.getnchannels() * 2
                if (
                    audio.getsampwidth() != 2
                    or audio.getnchannels() not in (1, 2)
                    or not 8000 <= rate <= 96000
                    or not 1 <= audio.getnframes() / rate <= 30
                    or len(audio.readframes(audio.getnframes())) != size
                ):
                    raise ValueError("Invalid PCM reference audio")
        except (ValueError, wave.Error, EOFError) as exc:
            raise ValueError("Invalid reference WAV") from exc
        return self

    def options(self):
        reference = (
            (base64.b64decode(self.reference_audio), self.reference_text.strip(), self.embedding_only)
            if self.reference_audio
            else None
        )
        return {"language": self.language, "reference": reference}


class Voice:
    def __init__(self, device=None, engine="standard"):
        import torch
        from qwen_tts import Qwen3TTSModel

        device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.device = device
        self.engine = engine
        torch.set_num_threads(4)
        self.lock = threading.Lock()
        start = time.perf_counter()
        if engine == "faster":
            from faster_qwen3_tts import FasterQwen3TTS

            self.model = FasterQwen3TTS.from_pretrained(
                str(MODEL_DIR), device=device, dtype=torch.bfloat16, max_seq_len=1024
            )
            base = self.model.model
            self.model._warmup(prefill_len=100)
        else:
            self.model = Qwen3TTSModel.from_pretrained(
                str(MODEL_DIR),
                device_map=device,
                dtype=torch.float32 if device == "cpu" else torch.bfloat16,
                attn_implementation="sdpa",
            )
            base = self.model
        self.base = base
        self.prompts = OrderedDict()
        self.prompt = None
        if (REFERENCE_DIR / "reference.wav").is_file() and (
            REFERENCE_DIR / "reference.txt"
        ).is_file():
            self.prompt = base.create_voice_clone_prompt(
                ref_audio=str(REFERENCE_DIR / "reference.wav"),
                ref_text=(REFERENCE_DIR / "reference.txt")
                .read_text(encoding="utf-8-sig")
                .strip(),
                x_vector_only_mode=False,
            )
        if engine == "faster" and self.prompt is not None:
            # Initialize codec CUDA kernels before advertising readiness, so
            # the user's first reply gets the same latency as later replies.
            for _chunk in self.model.generate_voice_clone_streaming(
                text="系统运行正常。",
                language="Chinese",
                voice_clone_prompt=self.prompt,
                non_streaming_mode=True,
                max_new_tokens=128,
                chunk_size=4,
            ):
                pass
        print(
            json.dumps(
                {
                    "ready": True,
                    "load_seconds": time.perf_counter() - start,
                    "device": "cpu"
                    if device == "cpu"
                    else torch.cuda.get_device_name(0),
                }
            ),
            flush=True,
        )

    @staticmethod
    def chunks(text, language="Chinese"):
        # Keep the English spelling from changing the Mandarin pronunciation.
        if language == "Chinese":
            text = re.sub(r"\bjarvis\b", "贾维斯", text, flags=re.IGNORECASE)
        sentences = re.findall(r"[^。！？.!?\n]+[。！？.!?]?|\n", text)
        chunks = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) > 100 and current.strip():
                chunks.append(current.strip())
                current = ""
            while len(sentence) > 150:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.append(sentence[:150])
                sentence = sentence[150:]
            current += sentence
        if current.strip():
            chunks.append(current.strip())
        if not chunks:
            raise ValueError("Speech text is empty")
        return chunks

    def _reference_prompt(self, reference):
        if reference is None:
            if self.prompt is None:
                raise ValueError("Built-in JARVIS reference assets are missing")
            return self.prompt
        data, text, embedding_only = reference
        key = hashlib.sha256(data + text.encode("utf-8") + bytes([embedding_only])).hexdigest()
        if key not in self.prompts:
            import numpy as np

            with wave.open(io.BytesIO(data), "rb") as audio:
                rate = audio.getframerate()
                samples = np.frombuffer(
                    audio.readframes(audio.getnframes()), dtype="<i2"
                ).astype(np.float32)
                samples = (
                    samples.reshape(-1, audio.getnchannels()).mean(axis=1) / 32768.0
                )
            self.prompts[key] = self.base.create_voice_clone_prompt(
                ref_audio=(samples, rate), ref_text=text or None, x_vector_only_mode=embedding_only
            )
            if len(self.prompts) > 4:
                self.prompts.popitem(last=False)
        self.prompts.move_to_end(key)
        return self.prompts[key]

    def synthesize(
        self, text: str, speed: float = 1.0, *, language="Chinese", reference=None
    ) -> bytes:
        import numpy as np
        import soundfile as sf
        import torch

        chunks = self.chunks(text, language)
        with self.lock:
            prompt = self._reference_prompt(reference)
            torch.manual_seed(42)
            audio = []
            for chunk in chunks:
                waves, rate = self.model.generate_voice_clone(
                    text=chunk,
                    language=language,
                    voice_clone_prompt=prompt,
                    non_streaming_mode=True,
                    max_new_tokens=512 if self.engine == "faster" else 1536,
                    **(
                        {"instruct": generation_instruction()}
                        if self.engine == "faster" and reference is None
                        else {}
                    ),
                )
                audio.append(waves[0])
            samples = np.concatenate(audio)
            samples = adjust_audio(
                samples,
                rate,
                speed=speed,
                pitch=pitch_semitones() if reference is None else 0.0,
            )
            buffer = io.BytesIO()
            sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
            return buffer.getvalue()

    def stream(
        self, text: str, speed: float = 1.0, *, language="Chinese", reference=None
    ):
        import numpy as np
        import torch

        if self.engine != "faster":
            raise RuntimeError("The active runtime does not support streaming")
        from qwen_voice_audio import TempoStream

        tempo = TempoStream(speed)
        with self.lock:
            prompt = self._reference_prompt(reference)
            torch.manual_seed(42)
            for chunk in self.chunks(text, language):
                for (
                    samples,
                    _rate,
                    _timing,
                ) in self.model.generate_voice_clone_streaming(
                    text=chunk,
                    language=language,
                    voice_clone_prompt=prompt,
                    non_streaming_mode=True,
                    max_new_tokens=512,
                    chunk_size=4,
                    **(
                        {"instruct": generation_instruction()}
                        if reference is None
                        else {}
                    ),
                ):
                    adjusted = tempo.process(samples)
                    if len(adjusted):
                        yield (np.clip(adjusted, -1, 1) * 32767).astype("<i2").tobytes()
            adjusted = tempo.finish()
            if len(adjusted):
                yield (np.clip(adjusted, -1, 1) * 32767).astype("<i2").tobytes()


def create_app(voice, identity=IDENTITY):
    import math

    from fastapi import FastAPI, HTTPException, Response
    from fastapi.responses import StreamingResponse

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health():
        return {
            "identity": identity,
            "ready": True,
            "voice_id": "jarvis-high",
            "reference_api": 1, "embedding_only_api": 1,
            "device": voice.device,
            "pitch_semitones": pitch_semitones(),
            "engine": voice.engine,
            "streaming": voice.engine == "faster",
            "loaded": voice.voice is not None,
            "busy": voice.lock.locked(),
            "suspended": voice.suspended.is_set(),
        }

    @app.post("/suspend")
    def suspend():
        if not voice.suspend():
            raise HTTPException(409, "Voice generation is active")
        return {"loaded": False, "suspended": True}

    @app.post("/resume")
    def resume():
        voice.resume()
        return {"loaded": voice.voice is not None, "suspended": False}

    @app.post("/synthesize")
    def synthesize(body: SynthesisRequest):
        if not math.isfinite(body.speed):
            raise HTTPException(422, "Invalid speed")
        return Response(
            content=voice.synthesize(body.text, body.speed, **body.options()),
            media_type="audio/wav",
            headers={"X-Voice-Id": body.voice_id},
        )

    @app.post("/stream")
    def stream(body: SynthesisRequest):
        if voice.engine != "faster":
            raise HTTPException(503, "Streaming requires the optimized GPU runtime")
        if not math.isfinite(body.speed):
            raise HTTPException(422, "Invalid speed")
        return StreamingResponse(
            voice.stream(body.text, body.speed, **body.options()),
            media_type="audio/pcm",
            headers={"X-Sample-Rate": "24000", "X-Voice-Id": body.voice_id},
        )

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--cpu-preview", action="store_true")
    parser.add_argument("--port", type=int, default=3337)
    parser.add_argument("--identity", default=IDENTITY)
    parser.add_argument("--engine", choices=("standard", "faster"), default="standard")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda:0"), default="auto")
    arguments = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", arguments.identity):
        parser.error("--identity contains unsupported characters")
    # Separate assistant processes share one GPU worker. A second launch exits
    # cleanly while its client waits for the original worker's health endpoint.
    import msvcrt

    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    worker_lock = (ROOT / "logs/qwen-tts-worker.lock").open("a+b")
    worker_lock.seek(0)
    if not worker_lock.read(1):
        worker_lock.write(b"0")
        worker_lock.flush()
    worker_lock.seek(0)
    try:
        msvcrt.locking(worker_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("The JARVIS Mandarin worker is already running", flush=True)
        return
    os.environ["HF_HUB_OFFLINE"] = "1"
    if arguments.preview or arguments.cpu_preview:
        voice = Voice("cpu" if arguments.cpu_preview else None, arguments.engine)
        start = time.perf_counter()
        output = ROOT / "logs/jarvis-high-chinese.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(
            voice.synthesize(
                "你好，我是贾维斯。所有系统运行正常。今天有什么需要我帮忙的？"
            )
        )
        print(
            json.dumps(
                {"path": str(output), "synthesis_seconds": time.perf_counter() - start}
            ),
            flush=True,
        )
        return

    import torch

    device = arguments.device
    if device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if arguments.engine == "faster" and device == "cpu":
        raise RuntimeError(
            "The optimized voice engine requires CUDA; use standard on CPU"
        )
    voice = VoicePool(device=device, engine=arguments.engine)

    import uvicorn

    uvicorn.run(
        create_app(voice, arguments.identity),
        host="127.0.0.1",
        port=arguments.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
