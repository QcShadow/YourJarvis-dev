"""Streaming must start playback before synthesis finishes and release on stop."""

import asyncio
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.speech.assistant import NativeVoiceRuntime
from openjarvis.speech.jarvis_tts import JarvisTTSBackend


@pytest.mark.anyio
async def test_native_playback_starts_before_second_chunk_is_generated():
    played = threading.Event()
    closed = threading.Event()
    order = []
    output = MagicMock()
    output.write.side_effect = lambda _pcm: (order.append("played"), played.set())

    def stream(text, **kwargs):
        try:
            order.append("first")
            yield b"\x00\x00" * 1024, 24000
            assert played.wait(2), "Playback waited for the entire generation"
            order.append("second")
            yield b"\x00\x00" * 1024, 24000
        finally:
            closed.set()

    runtime = NativeVoiceRuntime(
        transcribe=MagicMock(),
        respond=MagicMock(),
        synthesize=MagicMock(),
        synthesize_stream=stream,
    )
    with patch.dict(
        sys.modules,
        {
            "sounddevice": SimpleNamespace(
                RawOutputStream=MagicMock(return_value=output)
            )
        },
    ):
        await asyncio.wait_for(runtime._say("系统运行正常。"), timeout=3)
    assert order[:3] == ["first", "played", "second"]
    assert closed.is_set()
    output.close.assert_called_once()


def test_streaming_backend_closes_http_response_when_playback_stops():
    backend = JarvisTTSBackend()
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"X-Sample-Rate": "24000", "X-Voice-Id": "jarvis-high"}
    response.read.side_effect = [b"\x00\x00" * 1024, b"\x00\x00" * 1024]
    with (
        patch.object(backend, "_ensure_worker"),
        patch("urllib.request.urlopen", return_value=response),
    ):
        iterator = backend.synthesize_stream("你好", voice_id="zm_yunjian")
        assert next(iterator)[1] == 24000
        iterator.close()
    response.__exit__.assert_called_once()
    assert response.read.call_count == 1


@pytest.mark.anyio
async def test_first_sentence_is_spoken_while_llm_is_still_generating():
    spoken = asyncio.Event()
    calls = []

    async def respond(history, options):
        yield {"text": "系统运行正常。"}
        await asyncio.wait_for(spoken.wait(), timeout=1)
        yield {"text": "详细检查结果已准备好。"}

    async def say(text, options):
        calls.append(text)
        spoken.set()

    runtime = NativeVoiceRuntime(
        transcribe=MagicMock(),
        respond=respond,
        synthesize=MagicMock(),
        synthesize_stream=MagicMock(),
    )
    runtime._say = say
    runtime.armed_until = time.monotonic() + 5
    await runtime.handle_transcript("检查系统")
    assert calls == ["系统运行正常。", "详细检查结果已准备好。"]
    assert runtime.messages[-1]["content"] == "系统运行正常。详细检查结果已准备好。"
