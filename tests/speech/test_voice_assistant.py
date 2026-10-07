"""Background voice must segment real utterances and gate actions on wake."""

import asyncio
import io
import struct
import sys
import time
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.speech.assistant import (
    NativeVoiceRuntime,
    UtteranceSegmenter,
    VoiceOptions,
    extract_background_command,
    extract_interrupt,
    extract_wake_command,
    speech_chunks,
    speech_detail_switch,
    spoken_reply,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def frame(level=0):
    return struct.pack("<320h", *([level, -level] * 160))


def test_segmenter_keeps_onset_and_waits_through_short_pause():
    vad = UtteranceSegmenter(silence_ms=900)
    for _ in range(20):
        assert vad.feed(frame()) is None
    for _ in range(15):
        assert vad.feed(frame(900)) is None
    for _ in range(20):  # A 400ms pause inside the sentence.
        assert vad.feed(frame()) is None
    for _ in range(10):
        assert vad.feed(frame(1000)) is None
    for _ in range(44):
        assert vad.feed(frame()) is None
    audio = vad.feed(frame())
    assert audio
    with wave.open(io.BytesIO(audio)) as wav:
        samples = struct.unpack(
            "<" + "h" * wav.getnframes(), wav.readframes(wav.getnframes())
        )
    assert 900 in samples and 1000 in samples
    assert samples[: 320 * 10] == (0,) * (320 * 10)  # Leading pre-roll.
    assert len(samples) < (15 + 20 + 10 + 45 + 15) * 320  # Trim end pause.


def test_brief_click_is_not_a_command_and_next_utterance_is_clean():
    vad = UtteranceSegmenter(silence_ms=900)
    vad.feed(frame(3000))
    for _ in range(50):
        assert vad.feed(frame()) is None
    for _ in range(15):
        vad.feed(frame(1000))
    audio = None
    for _ in range(45):
        audio = vad.feed(frame())
    assert audio
    assert struct.pack("<h", 3000) not in audio[44:]


def test_adaptive_endpoint_waits_longer_for_slow_phrasing():
    vad = UtteranceSegmenter(silence_ms=1400)
    for _ in range(15):
        assert vad.feed(frame(1000)) is None
    for _ in range(40):  # An 800 ms thinking pause within the sentence.
        assert vad.feed(frame()) is None
    for _ in range(15):
        assert vad.feed(frame(1000)) is None
    assert vad.end_pause_ms() == 2000
    for _ in range(99):
        assert vad.feed(frame()) is None
    assert vad.feed(frame()) is not None


def test_long_request_gets_progressive_endpoint_room_but_short_command_does_not():
    long_request = UtteranceSegmenter(silence_ms=1400)
    for _ in range(410):
        assert long_request.feed(frame(1000)) is None
    for _ in range(89):
        assert long_request.feed(frame()) is None
    assert long_request.feed(frame()) is not None

    short_command = UtteranceSegmenter(silence_ms=1400)
    for _ in range(15):
        assert short_command.feed(frame(1000)) is None
    for _ in range(69):
        assert short_command.feed(frame()) is None
    assert short_command.feed(frame()) is not None


def test_segmenter_learns_speakers_pause_cadence_across_utterances():
    vad = UtteranceSegmenter(silence_ms=1400)
    for _ in range(15):
        assert vad.feed(frame(1000)) is None
    for _ in range(50):  # A one-second thinking pause teaches this session.
        assert vad.feed(frame()) is None
    for _ in range(15):
        assert vad.feed(frame(1000)) is None
    for _ in range(109):
        assert vad.feed(frame()) is None
    assert vad.feed(frame()) is not None
    assert vad.learned_pause_ms == 1000
    assert set(vad.last_metrics) == {
        "utterance_ms",
        "voiced_ms",
        "endpoint_pause_ms",
        "learned_pause_ms",
        "noise_level",
    }
    assert vad.last_metrics["utterance_ms"] == 1800.0
    assert vad.last_metrics["voiced_ms"] == 600.0
    assert vad.last_metrics["endpoint_pause_ms"] == 2200.0
    assert vad.last_metrics["learned_pause_ms"] == 1000.0
    assert all(isinstance(value, float) for value in vad.last_metrics.values())

    for _ in range(15):
        assert vad.feed(frame(1000)) is None
    for _ in range(109):
        assert vad.feed(frame()) is None
    assert vad.feed(frame()) is not None


@pytest.mark.anyio
async def test_capture_fault_then_stop_does_not_cancel_tool_drain_twice():
    runtime, _ = make_runtime()
    entered, release, draining = asyncio.Event(), asyncio.Event(), asyncio.Event()
    later = []

    async def respond(history, options):
        task = asyncio.create_task(release.wait())
        entered.set()
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            draining.set()
            await asyncio.shield(task)
            raise
        later.append("next tool")
        yield {"text": "done"}

    runtime.respond = respond
    await runtime._dispatch_transcript("嘿贾维斯，处理任务")
    await asyncio.wait_for(entered.wait(), 1)
    runtime._capture_error("temporary capture fault")
    await asyncio.wait_for(draining.wait(), 1)
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0.03)
    assert not stopping.done()
    release.set()
    await asyncio.wait_for(stopping, 1)
    assert not later and runtime.phase == "stopped"


@pytest.mark.anyio
async def test_output_language_and_voice_cache_do_not_follow_transcript_text():
    runtime, _ = make_runtime()
    runtime.options = VoiceOptions(language="zh", output_language="en", speak=False)
    await runtime.handle_transcript("嘿贾维斯")
    assert runtime.messages[-1]["content"] == "I'm here."
    calls = []
    runtime.synthesize = lambda text, **kw: (
        calls.append(kw) or SimpleNamespace(audio=b"a")
    )
    first = VoiceOptions(voice_profile="kokoro-zh-yunjian")
    second = VoiceOptions(
        voice_profile="jarvis-multilingual", character_id="mcu-jarvis"
    )
    runtime._ack_audio(first)
    runtime._ack_audio(second)
    assert len(calls) == 2
    assert calls[0]["voice_profile"] != calls[1]["voice_profile"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hey Jarvis, open the browser", (True, "open the browser")),
        ("嘿，贾维斯。打开浏览器", (True, "打开浏览器")),
        ("嘿，賈維斯", (True, "")),
        ("黑贾维斯。", (True, "")),
        ("嘿 贾 维 思，打开浏览器", (True, "打开浏览器")),
        ("贾维斯，打开浏览器", (True, "打开浏览器")),
        ("Jarvis, open the browser", (True, "open the browser")),
        ("Shanghai is nice", (False, "")),
        ("They Jarvis is a name", (False, "")),
        ("你好", (False, "")),
    ],
)
def test_wake_phrase_boundaries(text, expected):
    assert extract_wake_command(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("后台执行，整理这批文件", "整理这批文件"),
        ("交给后台处理：明天提醒我", "明天提醒我"),
        ("run this in the background summarize the notes", "summarize the notes"),
        ("请后台执行这个", None),
        ("后台执行", None),
    ],
)
def test_background_delegation_requires_explicit_nonempty_request(text, expected):
    assert extract_background_command(text) == expected


def test_spoken_reply_is_short_complete_and_hides_thoughts_and_code():
    text = (
        "<think>秘密</think>我是 JARVIS。已经处理好了。\n```python\nsecret()\n```"
        + "详细说明。" * 40
    )
    result = spoken_reply(text)
    assert result == "我是 贾维斯。已经处理好了。"
    assert len(result) <= 90
    assert spoken_reply("长" * 300) == "详细内容已放在页面上。"


def test_speech_chunks_follow_sentences_and_bound_long_clauses():
    assert speech_chunks("第一句。第二句。", "zh", 8) == ["第一句。第二句。"]
    assert speech_chunks("第一句话。第二句话。", "zh", 8) == [
        "第一句话。",
        "第二句话。",
    ]
    chunks = speech_chunks(
        "这是一段比较长的说明，需要在自然的逗号位置停顿，然后继续完成后半句话。",
        "zh",
        16,
    )
    assert len(chunks) > 1
    assert all(len(chunk) <= 17 for chunk in chunks)
    assert "自然的逗号位置" in "".join(chunks)


def test_interrupts_are_explicit_leading_configurable_controls():
    assert extract_interrupt("停一下，改成英文") == (True, "改成英文")
    assert extract_interrupt("STOP. Read the next file") == (True, "Read the next file")
    assert extract_interrupt("stopping this is risky") == (False, "")
    assert extract_interrupt("告诉我暂停的方法") == (False, "")
    assert extract_interrupt("停一下", ()) == (False, "")
    assert extract_interrupt("等等。", ("等等",)) == (True, "")
    assert extract_interrupt("暂停吧。") == (True, "")


@pytest.mark.anyio
async def test_interrupt_cancels_generation_and_retains_partial_reply():
    runtime, calls = make_runtime()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def respond(history, options):
        calls.append(history)
        yield {"text": "正在分析。"}
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    runtime.respond = respond
    await runtime._dispatch_transcript("嘿贾维斯，分析文件")
    await asyncio.wait_for(started.wait(), 1)
    assert runtime.snapshot()["can_interrupt"]
    await runtime._dispatch_transcript("普通背景说话", controls_only=True)
    assert not cancelled.is_set() and len(calls) == 1
    await runtime._dispatch_transcript("停一下", controls_only=True)
    assert cancelled.is_set()
    assert runtime.messages[-1]["content"] == "正在分析。"
    assert runtime.messages[-1]["interrupted"] is True
    assert runtime.phase == "armed" and not runtime._busy.is_set()
    await runtime.stop()


@pytest.mark.anyio
async def test_sleep_gate_rejects_interrupt_without_wake_and_echo_is_ignored():
    runtime, calls = make_runtime()
    await runtime._dispatch_transcript("停一下，打开浏览器")
    assert runtime.phase == "listening" and not calls
    runtime._spoken_text = "你可以说停一下来打断我。"
    await runtime._dispatch_transcript("停一下", controls_only=True)
    assert runtime.armed_until == 0
    assert runtime.audio_metrics["echo_rejections"] == 1
    runtime.armed_until = time.monotonic() - 1
    await runtime._dispatch_transcript("打开浏览器")
    await runtime._turn_task
    assert not calls
    await runtime.stop()


@pytest.mark.anyio
async def test_interrupt_can_dispatch_revised_request_without_new_wake():
    runtime, calls = make_runtime()
    runtime.armed_until = time.monotonic() + 30
    await runtime._dispatch_transcript("停一下，介绍你自己")
    await runtime._turn_task
    assert calls[-1][-1]["content"] == "介绍你自己"
    await runtime.stop()


@pytest.mark.anyio
async def test_capture_remains_live_while_model_is_busy(monkeypatch):
    import queue

    microphone_frames = queue.Queue()
    transcriptions = iter(["嘿贾维斯，分析文件", "停一下"])
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Microphone:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, count):
            try:
                return microphone_frames.get(timeout=0.01), False
            except queue.Empty:
                return frame(), False

    async def respond(history, options):
        yield {"text": "正在分析。"}
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(RawInputStream=lambda **kw: Microphone()),
    )
    runtime = NativeVoiceRuntime(
        transcribe=lambda *args, **kw: SimpleNamespace(text=next(transcriptions)),
        respond=respond,
        synthesize=MagicMock(),
    )
    await runtime.start(VoiceOptions(speak=False))
    try:
        for sample in [frame(1000)] * 15 + [frame()] * 75:
            microphone_frames.put(sample)
        await asyncio.wait_for(started.wait(), 2)
        assert runtime._busy.is_set()
        for sample in [frame(1000)] * 15 + [frame()] * 40:
            microphone_frames.put(sample)
        await asyncio.wait_for(cancelled.wait(), 2)

        async def rearmed():
            while runtime.phase != "armed":
                await asyncio.sleep(0.01)

        await asyncio.wait_for(rearmed(), 1)
        assert runtime.last_transcript == "停一下"
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_interrupt_stops_audio_playback_before_rearming():
    import threading

    runtime, _ = make_runtime()
    runtime.options = VoiceOptions(speak=True)
    runtime.synthesize = lambda *args, **kw: SimpleNamespace(audio=b"audio")
    started, stopped = threading.Event(), threading.Event()

    def play(audio):
        started.set()
        runtime._interrupt.wait(2)
        stopped.set()

    runtime._play = play
    await runtime._dispatch_transcript("嘿贾维斯，介绍自己")
    assert await asyncio.to_thread(started.wait, 1)
    await runtime._dispatch_transcript("停一下", controls_only=True)
    assert stopped.is_set() and runtime.phase == "armed"
    assert runtime._play_task is None
    await runtime.stop()


@pytest.mark.anyio
async def test_standby_preserves_running_wake_listener_and_requires_new_wake():
    runtime, calls = make_runtime()
    runtime.running = True
    runtime.armed_until = time.monotonic() + 30
    await runtime.standby()
    assert runtime.running and not runtime._stop.is_set()
    assert runtime.snapshot()["foreground"] is False
    await runtime.handle_transcript("打开浏览器")
    assert not calls
    await runtime.handle_transcript("嘿贾维斯")
    assert runtime.foreground is True and runtime.phase == "armed"
    await runtime.stop()


@pytest.mark.anyio
async def test_background_notification_waits_for_standby_and_does_not_interrupt_turn():
    runtime, _ = make_runtime()
    spoken = []

    async def say(text, options=None):
        spoken.append(text)

    runtime._say = say
    runtime.options = VoiceOptions(speak=True)
    runtime.running = True
    runtime.foreground = True
    assert not await runtime.notify_background(
        {"status": "completed", "content": "任务结果已经准备好。"}
    )
    assert spoken == [] and runtime.snapshot()["pending_notifications"] == 1
    await runtime.standby()
    assert spoken == ["后台工作已完成。"]
    assert runtime.snapshot()["pending_notifications"] == 0
    await runtime.stop()


@pytest.mark.anyio
async def test_voice_background_command_queues_without_foreground_model():
    runtime, calls = make_runtime()
    queued = []

    async def delegate(history, options):
        queued.append((history, options))
        return {"id": "job-1"}

    runtime.delegate = delegate
    runtime.options = VoiceOptions(speak=False)
    await runtime.handle_transcript("嘿贾维斯，后台执行，整理这批文件")
    assert not calls
    assert queued and queued[0][0][-1]["content"] == "整理这批文件"
    assert runtime.messages[-1]["backgroundJobId"] == "job-1"
    assert runtime.messages[-1]["background"] is True
    assert "已交给后台处理" in runtime.messages[-1]["content"]


@pytest.mark.anyio
async def test_detail_words_expand_speech_and_keep_conversation_context():
    runtime, calls = make_runtime()
    spoken = []

    async def say(text, options=None):
        spoken.append(text)

    runtime._say = say
    await runtime.handle_transcript("嘿贾维斯，武汉有什么好玩的")
    brief = spoken[-1]
    session = runtime.session_id
    await runtime.handle_transcript("具体说说")
    assert runtime.session_id == session and runtime.speech_detail == "full"
    assert len(calls[-1]) == 3
    assert calls[-1][0]["content"] == "武汉有什么好玩的"
    assert (
        len(spoken[-1]) > len(brief) and spoken[-1] == runtime.messages[-1]["content"]
    )
    await runtime.handle_transcript("简单一点")
    assert runtime.speech_detail == "brief" and len(spoken[-1]) <= 90
    assert speech_detail_switch("tell me more") == "full"


def make_runtime():
    respond_calls = []

    async def respond(history, options):
        respond_calls.append(history)
        yield {"model": "fast"}
        yield {"text": "好的。"}
        yield {"text": "完整说明。" * 30}
        yield {"usage": {"prompt_tokens": 1, "completion_tokens": 4, "total_tokens": 5}}

    runtime = NativeVoiceRuntime(
        transcribe=MagicMock(),
        respond=respond,
        synthesize=MagicMock(),
    )
    runtime.options = VoiceOptions(speak=False)
    return runtime, respond_calls


@pytest.mark.anyio
async def test_tool_mode_retains_provenance_and_only_speaks_final_result():
    runtime, _ = make_runtime()
    spoken = []
    sources = [{"url": "https://example.com/source", "title": "Source"}]

    async def say(text, options=None):
        spoken.append(text)

    async def respond(history, options):
        yield {"mode": "tool"}
        yield {"text": "正在查询。"}
        yield {
            "tool_event": {
                "stage": "tool",
                "tool": "web_search",
                "arguments": '{"query":"武汉景点"}',
            }
        }
        assert runtime.phase == "searching"
        yield {
            "tool_event": {
                "stage": "tool_complete",
                "tool": "web_search",
                "success": True,
                "result": "Actual result",
                "latency": 1200,
                "metadata": {"sources": sources},
            }
        }
        yield {"text": "可以去东湖。"}
        assert spoken == ["我在。"]  # Pre-tool promises must not start early speech.
        yield {"final_text": "可以去东湖。"}

    runtime.respond = respond
    runtime._say = say
    runtime.options = VoiceOptions(speak=True)
    runtime.synthesize_stream = MagicMock()  # Enable the early-speech code path.
    await runtime.handle_transcript("嘿贾维斯，武汉有什么好玩的")
    answer = runtime.messages[-1]
    assert answer["content"] == "可以去东湖。"
    assert spoken == ["我在。", "可以去东湖。"]
    assert answer["toolCalls"][0]["status"] == "success"
    assert answer["toolCalls"][0]["latency"] == 1200
    assert answer["toolCalls"][0]["metadata"]["sources"] == sources


@pytest.mark.anyio
async def test_standby_phrase_from_speaker_echo_cannot_pause_the_listener():
    runtime, calls = make_runtime()
    runtime.armed_until = time.monotonic() + 30
    runtime.foreground = True
    runtime._spoken_text = "你可以说先暂停吧进入后台。"
    await runtime._dispatch_transcript("先暂停吧", controls_only=True)
    assert runtime.foreground and runtime.armed_until > time.monotonic()
    assert not calls
    assert runtime.audio_metrics["echo_rejections"] == 1
    await runtime.stop()


@pytest.mark.anyio
async def test_voice_detail_followup_preserves_real_search_context_and_session():
    runtime, _ = make_runtime()
    original_date = "2026-09-30T01:00:00Z"
    runtime.messages = [
        {"id": "u", "role": "user", "content": "武汉有什么好玩的", "timestamp": 0},
        {
            "id": "a",
            "role": "assistant",
            "content": "可以去黄鹤楼",
            "timestamp": 0,
            "toolCalls": [
                {
                    "tool": "web_search",
                    "status": "success",
                    "arguments": '{"query":"武汉旅游"}',
                    "result": "黄鹤楼原始介绍",
                    "metadata": {
                        "sources": [
                            {
                                "url": "https://example.com/source",
                                "title": "Source",
                                "retrieved_at": original_date,
                            }
                        ]
                    },
                }
            ],
        },
    ]
    runtime.armed_until = time.monotonic() + 30
    session = runtime.session_id

    async def respond(history, options):
        assert options.speech_detail == "full"
        assert any(
            m["role"] == "tool" and "黄鹤楼原始介绍" in m["content"] for m in history
        )
        yield {"text": "根据先前查到的资料，黄鹤楼可以登高。"}

    runtime.respond = respond
    await runtime.handle_transcript("具体说说")
    assert runtime.session_id == session
    assert runtime.messages[-1]["sourceContext"][0]["retrieved_at"] == original_date
    assert "toolCalls" not in runtime.messages[-1]  # No fictitious new search.
    await runtime.handle_transcript("嘿贾维斯")
    assert runtime.session_id != session
    assert "sourceContext" not in runtime.messages[-1]


@pytest.mark.anyio
async def test_only_wake_and_followups_execute_and_full_text_is_retained():
    runtime, calls = make_runtime()
    await runtime.handle_transcript("打开浏览器")
    assert not calls and not runtime.messages
    await runtime.handle_transcript("嘿贾维斯，介绍你自己")
    assert len(calls) == 1
    assert len(runtime.messages[-1]["content"]) > 90
    assert runtime.messages[-1]["usage"]["total_tokens"] == 5
    await runtime.handle_transcript("再说一句")
    assert len(calls) == 2
    assert len(calls[-1]) == 3
    await runtime.handle_transcript("结束对话")
    await runtime.handle_transcript("打开浏览器")
    assert len(calls) == 2
    runtime.armed_until = time.monotonic() - 1
    await runtime.handle_transcript("继续")
    assert len(calls) == 2


@pytest.mark.anyio
async def test_wake_without_command_arms_but_does_not_call_model():
    runtime, calls = make_runtime()
    await runtime.handle_transcript("Hey Jarvis")
    assert runtime.phase == "armed" and not calls
    assert runtime.messages[-1]["content"] == "我在。"
    assert runtime.last_transcript == "Hey Jarvis"


@pytest.mark.anyio
async def test_each_explicit_wake_opens_new_session_followups_stay_together():
    runtime, calls = make_runtime()
    await runtime.handle_transcript("嘿，賈維斯")
    first = runtime.session_id
    assert runtime.last_transcript == "嘿，贾维斯"
    await runtime.handle_transcript("請介紹你自己")
    assert runtime.session_id == first
    assert calls[-1][-1]["content"] == "请介绍你自己"
    await runtime.handle_transcript("Hey Jarvis, explain again")
    assert runtime.session_id != first
    assert calls[-1] == [{"role": "user", "content": "explain again"}]
    assert runtime.wake_count == 2


@pytest.mark.anyio
async def test_wake_acknowledgement_plays_before_model_and_is_cached():
    events = []

    async def respond(history, options):
        events.append("model")
        yield {"text": "收到。"}

    def synthesize(text, **kwargs):
        events.append("synth:" + text)
        return SimpleNamespace(audio=text.encode())

    runtime = NativeVoiceRuntime(
        transcribe=MagicMock(), respond=respond, synthesize=synthesize
    )
    runtime._play = lambda audio: events.append("play:" + audio.decode())
    await runtime.handle_transcript("嘿贾维斯，介绍你自己")
    assert events.index("play:我在。") < events.index("model")
    await runtime.handle_transcript("嘿贾维斯")
    assert events.count("synth:我在。") == 1
    assert events.count("play:我在。") == 2


@pytest.mark.anyio
async def test_stop_waits_for_playback_before_restart_clears_stop_signal():
    import threading

    runtime, _ = make_runtime()
    started, finished = threading.Event(), threading.Event()

    def playback(audio):
        started.set()
        runtime._stop.wait(1)
        time.sleep(0.03)
        assert runtime._stop.is_set()
        finished.set()

    runtime._play = playback
    runtime._play_task = asyncio.create_task(asyncio.to_thread(runtime._play, b""))
    await asyncio.to_thread(started.wait, 1)
    await runtime.stop()
    assert finished.is_set() and runtime._play_task is None


@pytest.mark.anyio
async def test_streaming_playback_synthesizes_detailed_reply_in_natural_chunks(
    monkeypatch,
):
    synthesized = []
    played = []

    def synthesize_stream(text, **kwargs):
        synthesized.append(text)
        yield b"\0\0" * 160, 16000

    class Output:
        def start(self):
            pass

        def write(self, pcm):
            played.append(pcm)

        def stop(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(RawOutputStream=lambda **kwargs: Output()),
    )
    runtime = NativeVoiceRuntime(
        transcribe=MagicMock(),
        respond=MagicMock(),
        synthesize=MagicMock(),
        synthesize_stream=synthesize_stream,
    )
    detailed = "开场说明。" + "甲" * 80 + "。" + "乙" * 80 + "。"
    await asyncio.to_thread(
        runtime._play_stream,
        detailed,
        VoiceOptions(speak=True, output_language="zh"),
        asyncio.get_running_loop(),
    )
    assert len(synthesized) == 2
    assert "开场说明" in synthesized[0] and "乙" * 20 in synthesized[1]
    assert len(played) == 2


@pytest.mark.anyio
async def test_start_and_stop_release_capture_thread(monkeypatch):
    class Microphone:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            closed.append(True)

        def read(self, count):
            time.sleep(0.01)
            return frame(), False

    closed = []
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(RawInputStream=lambda **kw: Microphone()),
    )
    runtime, _ = make_runtime()
    await runtime.start(VoiceOptions(speak=False))
    assert runtime.running and runtime._thread.is_alive()
    capture = runtime._thread
    await runtime.start(VoiceOptions(speak=False, language="en"))
    assert runtime._thread is not capture
    assert not capture.is_alive()  # Language changes restart, never duplicate.
    await runtime.stop()
    assert not runtime.running and runtime._thread is None
    assert closed == [True, True]
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "jarvis-voice"]
