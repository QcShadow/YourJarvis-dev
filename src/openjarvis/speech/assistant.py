"""Background, local microphone conversation, independent of a browser tab."""

from __future__ import annotations

import asyncio
import io
import queue
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from openjarvis.speech.text import normalize_transcript
from openjarvis.speech.voice_io import _frames_to_wav, _rms


def extract_wake_command(text: str) -> tuple[bool, str]:
    text = normalize_transcript(text, "zh")
    match = re.search(
        r"(?:\bhey\b|\bhi\b|嘿|嗨|黑)[，,。.!！\s]*"
        r"(?:jarvis\b|贾[，,\s]*维[，,\s]*(?:斯|思)|杰维斯|加维斯)"
        r"|(?:^|[，,。.!！?？:：;；])(?:jarvis\b|贾[，,\s]*维[，,\s]*(?:斯|思)|杰维斯|加维斯)(?![A-Za-z])",
        text,
        re.IGNORECASE,
    )
    if not match:
        return False, ""
    return True, text[match.end() :].lstrip("，,。.!！?？ \t\n")


def extract_background_command(text: str) -> str | None:
    """Return an explicitly delegated task, never infer delegation implicitly."""
    match = re.match(
        r"^(?:后台(?:执行|处理)|交给后台(?:执行|处理)?|"
        r"稍后(?:处理|完成)|run this in the background|handle this in the background)"
        r"\s*[,，:：]?\s*(.+)$",
        text.strip(),
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def spoken_reply(text: str, language: str = "zh", detail: str = "brief") -> str:
    """Use complete, short sentences rather than reading a report or code."""
    text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text, flags=re.I)
    text = re.sub(r"^[\s\S]*?</think>\s*", "", text, flags=re.I)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*|[-*+]\s+|\d+[.)、]\s*)", "", text)
    text = re.sub(r"[*_`>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if detail == "full":
        return re.sub(
            r"\bjarvis\b", "贾维斯" if language == "zh" else "Jarvis", text, flags=re.I
        )
    zh = language == "zh"
    limit = 90 if zh else 180
    sentences = re.findall(r"[^。！？.!?]+[。！？.!?]?", text)
    result = ""
    for sentence in sentences[:2]:
        if len(result + sentence) > limit:
            break
        result += sentence
    if not result and text:
        # If the lead is one enormous sentence, stop at a clause boundary.
        lead = text[:limit]
        boundaries = list(re.finditer(r"[，,；;：:]", lead))
        result = lead[: boundaries[-1].start()] if boundaries else ""
        if not result:
            return "详细内容已放在页面上。" if zh else "The details are on screen."
    result = re.sub(
        r"\bjarvis\b", "贾维斯" if zh else "Jarvis", result, flags=re.I
    ).strip()
    if result and result[-1] not in "。！？.!?":
        result += "。" if zh else "."
    return result


def speech_chunks(
    text: str, language: str = "zh", max_chars: int | None = None
) -> list[str]:
    """Split spoken text at natural boundaries for low-latency TTS.

    The page keeps the complete answer.  This only changes how that answer is
    fed to the synthesizer so a detailed reply can begin promptly and pause at
    sentence or clause boundaries instead of becoming one very long request.
    """
    text = text.strip()
    if not text:
        return []
    limit = max_chars or (120 if language == "zh" else 240)
    if limit < 8:
        raise ValueError("Speech chunks must allow at least 8 characters")
    sentences = [
        part.strip()
        for part in re.findall(r".+?(?:[。！？!?]+|\.(?=\s|$)|$)", text)
        if part.strip()
    ]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current.strip())
            current = ""

    for sentence in sentences:
        separator = "" if language == "zh" or not current else " "
        if current and len(current) + len(separator) + len(sentence) <= limit:
            current += separator + sentence
            continue
        flush()
        while len(sentence) > limit:
            window = sentence[: limit + 1]
            boundaries = list(re.finditer(r"[，,；;：:]\s*", window))
            if language != "zh":
                boundaries.extend(re.finditer(r"\s+", window))
            useful = [match.end() for match in boundaries if match.end() >= limit // 2]
            cut = max(useful) if useful else limit
            part, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if part and part[-1] not in "。！？.!?，,；;：:":
                part += "，" if language == "zh" else ","
            if part:
                chunks.append(part)
        current = sentence
    flush()
    return chunks


DEFAULT_INTERRUPT_WORDS = ("停一下", "暂停", "别说了", "stop", "pause")


def speech_detail_switch(text: str) -> str | None:
    if re.match(
        r"^(?:具体说说|展开说说|详细一点|详细说说|讲详细点|"
        r"go into detail|tell me more|explain in detail)",
        text.strip(),
        re.I,
    ):
        return "full"
    if re.match(
        r"^(?:简单一点|大致说说|简短一点|简单说说|说重点|"
        r"keep it brief|briefly|summarize)",
        text.strip(),
        re.I,
    ):
        return "brief"
    return None


def extract_interrupt(text: str, words=DEFAULT_INTERRUPT_WORDS) -> tuple[bool, str]:
    """Match an explicit leading control phrase, not a word in an ordinary request."""
    text = normalize_transcript(text, "zh").strip()
    for word in sorted(words, key=len, reverse=True):
        word = normalize_transcript(word, "zh").strip()
        if not word:
            continue
        boundary = r"(?=$|[\s，,。.!！?？：:；;])" if word.isascii() else ""
        match = re.match(re.escape(word) + boundary, text, re.I)
        if match:
            remainder = text[match.end() :].lstrip("，,。.!！?？：:；; \t\n")
            if re.fullmatch(r"(?:一下|吧|一下吧|一下啊)[。.!！\s]*", remainder):
                remainder = ""
            return True, remainder
    return False, ""


class UtteranceSegmenter:
    """Adaptive energy VAD with pre-roll and a configurable end pause."""

    frame_ms = 20

    def __init__(self, silence_ms: int = 1800, adaptive: bool = True) -> None:
        self.silence_ms = silence_ms
        self.adaptive = adaptive
        self.noise = 90.0
        self.learned_pause_ms = 0.0
        self.last_metrics: dict[str, float] = {}
        self.reset()

    def reset(self) -> None:
        self.pre: deque[bytes] = deque(maxlen=15)
        self.frames: list[bytes] = []
        self.voiced = 0
        self.quiet = 0
        self.pause_ms = 0.0

    def end_pause_ms(self) -> float:
        # A speaker who pauses inside phrases gets more thinking room, while
        # short commands remain responsive. Bound the adjustment, not cadence.
        cadence_pause = max(self.pause_ms, self.learned_pause_ms)
        extra = max(0.0, cadence_pause * 1.5 - 600)
        # A first long hesitation cannot teach us the speaker's cadence before
        # it happens. Give longer utterances a small progressive allowance as
        # well, while keeping short commands on the configured baseline.
        spoken_span_ms = max(0, len(self.frames) - self.quiet) * self.frame_ms
        if spoken_span_ms >= 4000:
            extra += 200
        if spoken_span_ms >= 8000:
            extra += 200
        return self.silence_ms + min(800, extra) if self.adaptive else self.silence_ms

    def feed(self, frame: bytes) -> bytes | None:
        level = _rms(frame)
        loud = level > max(250.0, self.noise * 3.0)
        if not loud:
            self.noise = self.noise * 0.98 + min(level, 250.0) * 0.02
        if not self.frames:
            self.pre.append(frame)
            if not loud:
                return None
            self.frames = list(self.pre)
        else:
            self.frames.append(frame)
        if loud:
            if self.quiet * self.frame_ms >= 240:
                pause = self.quiet * self.frame_ms
                self.pause_ms = max(pause, self.pause_ms * 0.8)
                if self.adaptive:
                    bounded = min(1400.0, float(pause))
                    self.learned_pause_ms = (
                        bounded
                        if not self.learned_pause_ms
                        else self.learned_pause_ms * 0.75 + bounded * 0.25
                    )
            self.voiced += 1
            self.quiet = 0
        else:
            self.quiet += 1
        if (
            self.quiet * self.frame_ms < self.end_pause_ms()
            and len(self.frames) * self.frame_ms < 40000
        ):
            return None
        # Keep 200ms of the final pause; remove long trailing silence.
        trim = max(0, self.quiet - 10)
        frames = self.frames[:-trim] if trim else self.frames
        result = _frames_to_wav(frames, 16000) if self.voiced >= 8 else None
        if result is not None:
            self.last_metrics = {
                "utterance_ms": float(len(frames) * self.frame_ms),
                "voiced_ms": float(self.voiced * self.frame_ms),
                "endpoint_pause_ms": float(self.quiet * self.frame_ms),
                "learned_pause_ms": round(self.learned_pause_ms, 1),
                "noise_level": round(min(1.0, self.noise / 8000), 3),
            }
        self.reset()
        return result


@dataclass
class VoiceOptions:
    language: str = "zh"
    voice_id: str = "zm_yunjian"
    speed: float = 1.1
    silence_ms: int = 1800
    followup_seconds: float = 30.0
    speak: bool = True
    fast_model: str = "qwen3.5:9b"
    strong_model: str = "deepseek-r1:14b"
    automatic_routing: bool = True
    voice_profile: str = ""
    character_id: str = "jarvis-local"
    output_language: str = ""
    interrupt_words: tuple[str, ...] = DEFAULT_INTERRUPT_WORDS
    speech_detail: str = "brief"

    @property
    def response_language(self):
        return self.output_language or self.language


class NativeVoiceRuntime:
    """Own the microphone, conversation and playback until explicitly stopped.

    All text state is mutated on the asyncio loop. The capture thread only
    sends complete utterances; a bounded queue prevents old commands building
    up while the assistant is working. Audio is never written to disk here.
    """

    def __init__(
        self,
        *,
        transcribe: Callable[..., Any],
        respond: Callable[..., AsyncIterator[dict[str, Any]]],
        synthesize: Callable[..., Any],
        synthesize_stream: Callable[..., Any] | None = None,
        delegate: Callable[[list[dict[str, Any]], VoiceOptions], Awaitable[dict]]
        | None = None,
    ) -> None:
        self.transcribe = transcribe
        self.respond = respond
        self.synthesize = synthesize
        self.synthesize_stream = synthesize_stream
        self.delegate = delegate
        self.options = VoiceOptions()
        self.session_id = "voice-" + uuid.uuid4().hex[:12]
        self.messages: list[dict[str, Any]] = []
        self.revision = 0
        self.phase = "stopped"
        self.error = ""
        self.running = False
        self.last_transcript = ""
        self.input_level = 0.0
        self.wake_count = 0
        # Numeric-only audio diagnostics. Raw microphone audio is never retained.
        self.audio_metrics: dict[str, float] = {
            "utterance_ms": 0.0,
            "voiced_ms": 0.0,
            "endpoint_pause_ms": 0.0,
            "learned_pause_ms": 0.0,
            "noise_level": 0.0,
            "queue_delay_ms": 0.0,
            "transcription_ms": 0.0,
            "endpoint_to_dispatch_ms": 0.0,
            "queue_drops": 0.0,
            "echo_rejections": 0.0,
            "busy_ignored": 0.0,
        }
        self.armed_until = 0.0
        self._stop = threading.Event()
        self._busy = threading.Event()
        self._interrupt = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._turn_task: asyncio.Task | None = None
        self._play_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._ack_cache: dict[tuple, bytes] = {}
        self._synthesis_lock = threading.Lock()
        self._queue: asyncio.Queue[tuple[bytes, bool, float] | None] = asyncio.Queue(
            maxsize=1
        )
        self._notification_lock = asyncio.Lock()
        self._pending_notifications: deque[tuple[str, str]] = deque(maxlen=8)
        self.last_notification = ""
        self._spoken_text = ""
        self.foreground = True
        self.speech_detail = "brief"

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "error": self.error,
            "revision": self.revision,
            "session_id": self.session_id,
            "model": self.options.fast_model,
            "last_transcript": self.last_transcript,
            "input_level": self.input_level,
            "audio_metrics": dict(self.audio_metrics),
            "wake_count": self.wake_count,
            "followup_remaining": max(0, round(self.armed_until - time.monotonic(), 1)),
            "can_interrupt": bool(self._turn_task and not self._turn_task.done()),
            "foreground": self.foreground,
            "speech_detail": self.speech_detail,
            "last_notification": self.last_notification,
            "pending_notifications": len(self._pending_notifications),
            "messages": [dict(message) for message in self.messages],
        }

    def _status(self, phase: str, error: str = "") -> None:
        self.phase, self.error = phase, error
        self.revision += 1

    async def start(self, options: VoiceOptions) -> None:
        if self.running:
            if (
                self.options.silence_ms == options.silence_ms
                and self.options.language == options.language
                and self.options.response_language == options.response_language
                and self.options.voice_profile == options.voice_profile
                and self.options.voice_id == options.voice_id
                and self.options.character_id == options.character_id
            ):
                self.options = options
                return
        # An errored capture thread may have left a consumer waiting.
        await self.stop()
        self.options = options
        self.foreground = True
        self.speech_detail = options.speech_detail
        self.session_id = "voice-" + uuid.uuid4().hex[:12]
        self.messages = []
        self._stop.clear()
        self._busy.clear()
        self._interrupt.clear()
        self.armed_until = 0.0
        self._queue = asyncio.Queue(maxsize=1)
        for metric in self.audio_metrics:
            self.audio_metrics[metric] = 0.0
        self._status("starting")
        loop = asyncio.get_running_loop()
        ready = loop.create_future()

        def report_ready(error: str = "") -> None:
            if not ready.done():
                if error:
                    ready.set_exception(RuntimeError(error))
                else:
                    ready.set_result(None)

        def enqueue(audio: bytes, controls_only: bool, captured_at: float) -> None:
            if not self._stop.is_set() and self._queue.empty():
                self._queue.put_nowait((audio, controls_only, captured_at))
            elif not self._stop.is_set():
                self.audio_metrics["queue_drops"] += 1

        def capture() -> None:
            try:
                import sounddevice as sd

                segmenter = UtteranceSegmenter(options.silence_ms)
                controls_only = False
                with sd.RawInputStream(
                    samplerate=16000,
                    channels=1,
                    dtype="int16",
                    blocksize=320,
                ) as stream:
                    loop.call_soon_threadsafe(report_ready)
                    while not self._stop.is_set():
                        raw, overflow = stream.read(320)
                        self.input_level = round(min(1.0, _rms(bytes(raw)) / 8000), 3)
                        if overflow:
                            segmenter.reset()
                            controls_only = False
                            continue
                        controls_only = controls_only or self._busy.is_set()
                        segmenter.silence_ms = (
                            700 if controls_only else options.silence_ms
                        )
                        audio = segmenter.feed(bytes(raw))
                        if audio:
                            captured_at = time.monotonic()
                            loop.call_soon_threadsafe(
                                self.audio_metrics.update,
                                dict(segmenter.last_metrics),
                            )
                            loop.call_soon_threadsafe(
                                enqueue, audio, controls_only, captured_at
                            )
                            controls_only = False
                        elif not segmenter.frames:
                            controls_only = False
            except Exception as exc:
                message = str(exc)
                loop.call_soon_threadsafe(report_ready, message)
                loop.call_soon_threadsafe(self._capture_error, message)

        self._thread = threading.Thread(
            target=capture, name="jarvis-microphone", daemon=True
        )
        self._thread.start()
        try:
            await asyncio.wait_for(ready, timeout=8)
        except Exception:
            self._stop.set()
            await asyncio.to_thread(self._thread.join, 2)
            raise
        self.running = True
        self._status("listening")
        self._task = asyncio.create_task(self._consume(), name="jarvis-voice")
        if options.speak:
            self._warm_task = asyncio.create_task(
                asyncio.to_thread(self._ack_audio, options), name="jarvis-wake-audio"
            )
            self._warm_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )

    def _capture_error(self, message: str) -> None:
        self.running = False
        self._stop.set()
        self._interrupt.set()
        self._status("error", message)
        if self._task:
            self._task.cancel()
        if self._turn_task:
            if not self._turn_task.cancelling():
                self._turn_task.cancel()

    async def stop(self) -> None:
        self._stop.set()
        self._interrupt.set()
        self.running = False
        self.armed_until = 0.0
        self._pending_notifications.clear()
        self.last_notification = ""
        task, self._task = self._task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._cancel_turn()
        if self._thread:
            await asyncio.to_thread(self._thread.join, 2)
            if self._thread.is_alive():
                raise RuntimeError(
                    "Microphone capture did not stop; restart JARVIS "
                    "before enabling it again"
                )
            self._thread = None
        if self._play_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._play_task), timeout=2)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Voice playback did not stop") from exc
            finally:
                if self._play_task.done():
                    self._play_task = None
        self.input_level = 0.0
        self._busy.clear()
        self._status("stopped")

    async def _consume(self) -> None:
        while not self._stop.is_set():
            try:
                try:
                    queued = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if self.phase == "armed" and time.monotonic() >= self.armed_until:
                        self.foreground = False
                        self._status("listening")
                        await self._drain_notifications()
                    continue
                if queued is None:
                    return
                audio, controls_only, captured_at = queued
                transcribe_started = time.monotonic()
                self.audio_metrics["queue_delay_ms"] = round(
                    (transcribe_started - captured_at) * 1000, 1
                )
                if not self._busy.is_set():
                    self._status("transcribing")
                result = await asyncio.to_thread(
                    self.transcribe,
                    audio,
                    format="wav",
                    language=self.options.language,
                )
                transcribed_at = time.monotonic()
                self.audio_metrics["transcription_ms"] = round(
                    (transcribed_at - transcribe_started) * 1000, 1
                )
                self.audio_metrics["endpoint_to_dispatch_ms"] = round(
                    (transcribed_at - captured_at) * 1000, 1
                )
                if self._stop.is_set():
                    return
                await self._dispatch_transcript(result.text.strip(), controls_only)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._status("error", str(exc))

    async def _cancel_turn(self) -> None:
        """Stop speech, then drain any already-authorized tool execution."""
        self._interrupt.set()
        task = self._turn_task
        if task and not task.done():
            if not self._stop.is_set():
                self._status("interrupting")
            if not task.cancelling():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._play_task:
            await asyncio.shield(self._play_task)
            self._play_task = None
        self._turn_task = None
        self._busy.clear()

    async def standby(self) -> None:
        """Pause this conversation, not the always-on wake listener."""
        await self._cancel_turn()
        self.armed_until = 0
        self.foreground = False
        self._status("listening" if self.running else "stopped")
        await self._drain_notifications()

    async def notify_background(self, job: dict[str, Any]) -> bool:
        """Announce a completed background task when it is safe to speak."""
        status = str(job.get("status", "completed"))
        language = self.options.response_language
        if status == "completed":
            text = (
                "后台工作已完成。"
                if language == "zh"
                else "Background work is complete."
            )
        else:
            text = (
                "后台工作未完成。"
                if language == "zh"
                else "Background work did not finish."
            )
        # Do not read arbitrary task output aloud: background work may contain
        # private files, credentials, or other data that is safe on screen but
        # unsafe to announce in a room. The panel retains the full result.
        if not self.running or not self.options.speak or self._stop.is_set():
            return False
        async with self._notification_lock:
            if self.foreground or self._busy.is_set() or self._turn_task is not None:
                self._pending_notifications.append((status, text))
                self.revision += 1
                return False
            await self._speak_notification(text)
            return True

    async def _speak_notification(self, text: str) -> None:
        if not text or not self.running or not self.options.speak:
            return
        self.last_notification = text
        self._busy.set()
        try:
            await self._say(text, self.options)
        finally:
            self._busy.clear()
            self._status(
                "listening" if self.running and not self.foreground else "armed"
            )

    async def _drain_notifications(self) -> None:
        if not self.running or self.foreground or self._busy.is_set():
            return
        async with self._notification_lock:
            while self._pending_notifications and self.running and not self.foreground:
                _, text = self._pending_notifications.popleft()
                await self._speak_notification(text)

    async def _dispatch_transcript(
        self, text: str, controls_only: bool = False
    ) -> None:
        text = normalize_transcript(text, self.options.language).strip()
        if not text:
            return
        interrupted, remainder = extract_interrupt(text, self.options.interrupt_words)
        woke, _ = extract_wake_command(text)
        busy = bool(self._turn_task and not self._turn_task.done())
        # Apply echo filtering before *all* controls, including standby.
        if (busy or controls_only) and self._spoken_text:

            def compact(value):
                return re.sub(r"[\W_]+", "", value).casefold()

            if compact(text) and compact(text) in compact(self._spoken_text):
                self.audio_metrics["echo_rejections"] += 1
                return
        if re.fullmatch(
            r"(?:先暂停(?:一下)?吧?|暂停对话|回到后台|切回文字|"
            r"stop listening|pause conversation)[。.!！\s]*",
            text,
            re.I,
        ):
            if busy or time.monotonic() < self.armed_until:
                self.last_transcript = text
                await self.standby()
            return
        if (
            interrupted
            and not busy
            and not controls_only
            and time.monotonic() >= self.armed_until
        ):
            self._status("listening")
            return
        if busy or controls_only:
            if not (interrupted or woke):
                self.audio_metrics["busy_ignored"] += 1
                return
            await self._cancel_turn()
        if interrupted:
            self.last_transcript = text
            self.armed_until = time.monotonic() + self.options.followup_seconds
            self._status("armed")
            if not remainder:
                return
            text = remainder
        self._interrupt.clear()
        self._spoken_text = ""
        self._busy.set()

        async def run_turn():
            try:
                await self.handle_transcript(text)
            finally:
                self._busy.clear()

        self._turn_task = asyncio.create_task(run_turn(), name="jarvis-voice-turn")

    async def handle_transcript(self, text: str) -> None:
        options = self.options
        text = normalize_transcript(text, self.options.language)
        self.last_transcript = text
        woke, command = extract_wake_command(text)
        if woke:
            self.foreground = True
            self.speech_detail = options.speech_detail
            self.wake_count += 1
            self.session_id = "voice-" + uuid.uuid4().hex[:12]
            self.messages = []
            self._status("armed")
            if not command:
                now = int(time.time() * 1000)
                self.messages = [
                    {
                        "id": uuid.uuid4().hex,
                        "role": "user",
                        "content": text,
                        "timestamp": now,
                    },
                    {
                        "id": uuid.uuid4().hex,
                        "role": "assistant",
                        "content": "我在。"
                        if options.response_language == "zh"
                        else "I'm here.",
                        "timestamp": now,
                    },
                ]
            await self._say(
                "我在。" if options.response_language == "zh" else "I'm here.", options
            )
            self.armed_until = time.monotonic() + self.options.followup_seconds
        elif time.monotonic() < self.armed_until:
            command = text
        else:
            self._status("listening")
            return
        if re.fullmatch(
            r"(?:停止接听|结束对话|不用了|再见|先暂停(?:一下)?吧?|暂停对话|"
            r"回到后台|切回文字|stop listening|pause conversation|goodbye)[。.!！\s]*",
            command,
            re.I,
        ):
            self.armed_until = 0
            self.foreground = False
            self._status("listening")
            return
        if not command:
            self._status("armed")
            self.armed_until = time.monotonic() + self.options.followup_seconds
            self._status("armed")
            return
        detail = speech_detail_switch(command)
        if detail:
            self.speech_detail = detail
        from dataclasses import replace

        options = replace(options, speech_detail=self.speech_detail)
        delegated_text = extract_background_command(command) if self.delegate else None
        user_content = delegated_text or command
        now = int(time.time() * 1000)
        self.messages.append(
            {
                "id": uuid.uuid4().hex,
                "role": "user",
                "content": user_content,
                "timestamp": now,
            }
        )
        # Keep a bounded conversational context; durable memory lives separately.
        self.messages = self.messages[-60:]
        from openjarvis.speech.conversation import (
            build_conversation_history,
            inherited_sources,
        )

        history = build_conversation_history(self.messages)
        assistant: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": "",
            "timestamp": now,
        }
        sources = inherited_sources(self.messages)
        if sources:
            assistant["sourceContext"] = sources
        self.messages.append(assistant)
        if delegated_text and self.delegate is not None:
            self._status("queuing")
            try:
                job = await self.delegate(history, options)
                assistant["content"] = (
                    "已交给后台处理，完成后我会通知你。"
                    if options.response_language == "zh"
                    else (
                        "It is queued in the background. "
                        "I will notify you when it is done."
                    )
                )
                assistant["backgroundJobId"] = job.get("id", "")
                assistant["background"] = True
                self.revision += 1
                await self._say(assistant["content"], options)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                assistant["content"] = (
                    "后台任务暂时无法排队，请查看页面中的错误信息。"
                    if options.response_language == "zh"
                    else (
                        "The background task could not be queued. "
                        "Check the error on screen."
                    )
                )
                assistant["error"] = str(exc)
                self._status("error", str(exc))
                self.revision += 1
            self.armed_until = time.monotonic() + self.options.followup_seconds
            self._status("armed")
            return
        self._status("thinking")
        early_speech = None
        first_spoken = ""
        tool_mode = False
        try:
            async for event in self.respond(history, options):
                if self._stop.is_set():
                    return
                if event.get("text"):
                    assistant["content"] += event["text"]
                    self._status(self.phase if early_speech else "responding")
                    # Start TTS on the first complete sentence while the LLM
                    # continues writing. Keep the entire reply in text history.
                    if (
                        options.speak
                        and not tool_mode
                        and self.speech_detail == "brief"
                        and self.synthesize_stream is not None
                        and early_speech is None
                    ):
                        content = assistant["content"]
                        if "<think>" not in content.lower() and "```" not in content:
                            match = re.match(
                                r"^(.{1,90}?[。！？!?]|.{1,180}?[.]\s)", content
                            )
                            if match:
                                first_spoken = spoken_reply(
                                    match.group(0), options.response_language
                                )
                                early_speech = asyncio.create_task(
                                    self._say(first_spoken, options)
                                )
                if "mode" in event:
                    tool_mode = event["mode"] == "tool"
                if "final_text" in event:
                    assistant["content"] = event["final_text"]
                    self.revision += 1
                if "tool_event" in event:
                    info = event["tool_event"]
                    calls = assistant.setdefault("toolCalls", [])
                    if info["stage"] == "tool":
                        calls.append(
                            {
                                "id": uuid.uuid4().hex,
                                "tool": info["tool"],
                                "arguments": info.get("arguments", "{}"),
                                "status": "running",
                            }
                        )
                        self._status(
                            "searching" if info["tool"] == "web_search" else "thinking"
                        )
                    else:
                        call = next(
                            (
                                call
                                for call in reversed(calls)
                                if call["tool"] == info["tool"]
                                and call["status"] == "running"
                            ),
                            None,
                        )
                        if call is not None:
                            call.update(
                                status="success" if info["success"] else "error",
                                result=info.get("result", ""),
                                latency=info.get("latency", 0),
                                metadata=info.get("metadata", {}),
                            )
                        self.revision += 1
                if event.get("model"):
                    assistant["telemetry"] = {"model_id": event["model"]}
                if event.get("usage"):
                    assistant["usage"] = event["usage"]
            final_spoken = spoken_reply(
                assistant["content"], options.response_language, self.speech_detail
            )
            if early_speech is not None:
                await early_speech
                if final_spoken.startswith(first_spoken):
                    await self._say(final_spoken[len(first_spoken) :].strip(), options)
            else:
                await self._say(final_spoken, options)
        except asyncio.CancelledError:
            assistant["interrupted"] = True
            if not assistant["content"]:
                assistant["content"] = (
                    "已打断。" if options.response_language == "zh" else "Interrupted."
                )
            self.revision += 1
            raise
        except Exception as exc:
            if not assistant["content"]:
                assistant["content"] = (
                    "执行失败，请查看页面中的错误信息。"
                    if self.options.language == "zh"
                    else "The task failed. Check the error on screen."
                )
            self._status("error", str(exc))
            return
        finally:
            if early_speech is not None:
                if not early_speech.done():
                    early_speech.cancel()
                await asyncio.gather(early_speech, return_exceptions=True)
        self.armed_until = time.monotonic() + self.options.followup_seconds
        self._status("armed")

    async def _say(self, text: str, options: VoiceOptions | None = None) -> None:
        options = options or self.options
        if (
            not text
            or not options.speak
            or self._stop.is_set()
            or self._interrupt.is_set()
        ):
            return
        self._spoken_text = text
        self._status("synthesizing")
        if self.synthesize_stream is not None and text not in {"我在。", "I'm here."}:
            loop = asyncio.get_running_loop()
            self._play_task = asyncio.create_task(
                asyncio.to_thread(self._play_stream, text, options, loop)
            )
            await asyncio.shield(self._play_task)
            self._play_task = None
            return
        if text in {"我在。", "I'm here."}:
            audio = await asyncio.to_thread(self._ack_audio, options)
        else:
            audio = await asyncio.to_thread(self._synthesize_audio, text, options)
        if self._stop.is_set() or self._interrupt.is_set():
            return
        self._status("speaking")
        self._play_task = asyncio.create_task(asyncio.to_thread(self._play, audio))
        await asyncio.shield(self._play_task)
        self._play_task = None

    def _synthesize_audio(self, text: str, options: VoiceOptions) -> bytes:
        with self._synthesis_lock:
            return self.synthesize(
                text,
                voice_id=options.voice_id,
                speed=options.speed,
                output_format="wav",
                **(
                    {"voice_profile": options.voice_profile}
                    if options.voice_profile
                    else {}
                ),
            ).audio

    def _ack_audio(self, options: VoiceOptions) -> bytes:
        key = (
            options.response_language,
            options.voice_profile,
            options.voice_id,
            options.speed,
        )
        with self._synthesis_lock:
            if key not in self._ack_cache:
                if len(self._ack_cache) >= 4:
                    self._ack_cache.clear()
                self._ack_cache[key] = self.synthesize(
                    "我在。" if options.response_language == "zh" else "I'm here.",
                    voice_id=options.voice_id,
                    speed=options.speed,
                    output_format="wav",
                    **(
                        {"voice_profile": options.voice_profile}
                        if options.voice_profile
                        else {}
                    ),
                ).audio
            return self._ack_cache[key]

    def _play(self, audio: bytes) -> None:
        import sounddevice as sd
        import soundfile as sf

        samples, rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
        # A dedicated stream can stop promptly without touching another app's
        # sounddevice playback, and without relying on the WebView being visible.
        with sd.OutputStream(
            samplerate=rate, channels=samples.shape[1], dtype="float32"
        ) as output:
            for offset in range(0, len(samples), 1024):
                if self._stop.is_set() or self._interrupt.is_set():
                    break
                output.write(samples[offset : offset + 1024])

    def _play_stream(self, text, options, loop):
        """Overlap GPU generation with playback and bound queued audio."""
        import sounddevice as sd

        pending = queue.Queue(maxsize=8)
        cancelled = threading.Event()

        def put(value):
            while (
                not cancelled.is_set()
                and not self._stop.is_set()
                and not self._interrupt.is_set()
            ):
                try:
                    pending.put(value, timeout=0.05)
                    return
                except queue.Full:
                    continue

        def produce():
            iterator = None
            try:
                with self._synthesis_lock:
                    for spoken_chunk in speech_chunks(
                        text, options.response_language
                    ):
                        if (
                            cancelled.is_set()
                            or self._stop.is_set()
                            or self._interrupt.is_set()
                        ):
                            break
                        iterator = self.synthesize_stream(
                            spoken_chunk,
                            voice_id=options.voice_id,
                            speed=options.speed,
                            output_format="wav",
                            **(
                                {"voice_profile": options.voice_profile}
                                if options.voice_profile
                                else {}
                            ),
                        )
                        try:
                            for chunk in iterator:
                                if (
                                    cancelled.is_set()
                                    or self._stop.is_set()
                                    or self._interrupt.is_set()
                                ):
                                    break
                                put(chunk)
                        finally:
                            if hasattr(iterator, "close"):
                                iterator.close()
                            iterator = None
                put(None)
            except Exception as error:
                put(error)
            finally:
                if iterator is not None and hasattr(iterator, "close"):
                    iterator.close()

        producer = threading.Thread(
            target=produce, daemon=True, name="jarvis-tts-stream"
        )
        producer.start()
        output = None
        try:
            while not self._stop.is_set() and not self._interrupt.is_set():
                try:
                    chunk = pending.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                if isinstance(chunk, Exception):
                    raise chunk
                pcm, rate = chunk
                if output is None:
                    output = sd.RawOutputStream(
                        samplerate=rate, channels=1, dtype="int16"
                    )
                    output.start()
                    loop.call_soon_threadsafe(self._status, "speaking")
                if len(pcm) % 2:
                    raise ValueError("Streaming audio has an incomplete sample")
                output.write(pcm)
        finally:
            cancelled.set()
            if output is not None:
                if self._stop.is_set() or self._interrupt.is_set():
                    output.abort()
                else:
                    output.stop()
                output.close()
            producer.join(timeout=0.2)
