"""Saved consent, standby restoration and explicit off beat a slow startup."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import Request

from openjarvis.server.voice_lifecycle import restore_voice
from openjarvis.server.voice_routes import StartVoiceRequest, _start_voice
from openjarvis.speech.preferences import (
    load_preference,
    preference_path,
    save_preference,
)
from tests.server.test_voice_routes import app_with_stream


async def wait_until_standby(app):
    async with asyncio.timeout(2):
        while True:
            runtime = getattr(app.state, "voice_runtime", None)
            if runtime is not None and runtime.running and not runtime.foreground:
                return
            await asyncio.sleep(0.01)


def fake_start(app):
    async def start(body, request):
        runtime = SimpleNamespace(
            running=True,
            foreground=True,
            options=body,
            start=AsyncMock(),
            stop=AsyncMock(),
            standby=AsyncMock(),
        )

        async def standby():
            runtime.foreground = False

        async def stop():
            runtime.running = False

        runtime.standby.side_effect = standby
        runtime.stop.side_effect = stop
        runtime.snapshot = lambda: {
            "running": runtime.running,
            "foreground": runtime.foreground,
            "phase": "listening" if runtime.running else "stopped",
            "messages": [],
        }
        app.state.voice_runtime = runtime
        return runtime.snapshot()

    return start


def test_preferences_are_atomic_and_do_not_store_conversations(monkeypatch):
    body = StartVoiceRequest(
        language="en",
        voice_profile="piper-mcu-jarvis",
        character_id="mcu-jarvis",
        output_language="en",
    )
    save_preference(enabled=True, options=body.model_dump(mode="json"))
    previous = preference_path().read_text(encoding="utf-8")
    record = load_preference()
    assert record.enabled and record.options["voice_profile"] == "piper-mcu-jarvis"
    assert "messages" not in previous and "recordings" not in previous

    def fail_replace(*args):
        raise PermissionError("atomic replacement failed")

    monkeypatch.setattr("openjarvis.speech.preferences.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        save_preference(enabled=False)
    assert preference_path().read_text(encoding="utf-8") == previous
    assert not list(preference_path().parent.glob(".voice-pref-*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [None, False])
async def test_missing_or_disabled_consent_never_starts_microphone(monkeypatch, saved):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    start = AsyncMock()
    monkeypatch.setattr(voice_routes, "_start_voice", start)
    if saved is not None:
        save_preference(enabled=saved)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert not getattr(app.state, "voice_restore_task", None)
        start.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_preserves_exact_voice_options_and_enters_standby(monkeypatch):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    app.state.speech_backend = MagicMock()
    original = StartVoiceRequest(
        language="en",
        output_language="en",
        character_id="mcu-jarvis",
        voice_profile="piper-mcu-jarvis",
        silence_ms=2100,
        interrupt_words=["hold on"],
    )
    save_preference(enabled=True, options=original.model_dump(mode="json"))
    start = AsyncMock(side_effect=fake_start(app))
    monkeypatch.setattr(voice_routes, "_start_voice", start)
    async with app.router.lifespan_context(app):
        await wait_until_standby(app)
        runtime = app.state.voice_runtime
        assert runtime.running and not runtime.foreground
        assert start.call_args.args[0] == original
        runtime.standby.assert_awaited_once()
    runtime.stop.assert_awaited_once()
    assert load_preference().enabled  # Shutdown is not a user request for off.


@pytest.mark.asyncio
async def test_explicit_off_cancels_a_pending_slow_restore_and_stays_off(monkeypatch):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    app.state.speech_backend = MagicMock()
    entered, cancelled = asyncio.Event(), asyncio.Event()
    save_preference(enabled=True, options=StartVoiceRequest().model_dump(mode="json"))

    async def slow_start(body, request):
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    monkeypatch.setattr(voice_routes, "_start_voice", slow_start)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(entered.wait(), 1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            async with asyncio.timeout(1):
                result = await client.post("/v1/voice/stop")
            assert result.status_code == 200
            state = (await client.get("/v1/voice/state")).json()
            assert state["desired_enabled"] is False and not state["restoring"]
        assert cancelled.is_set() and not load_preference().enabled
    new_app = app_with_stream()
    async with new_app.router.lifespan_context(new_app):
        assert not getattr(new_app.state, "voice_restore_task", None)


@pytest.mark.asyncio
async def test_pause_keeps_enabled_and_changing_voice_preserves_standby(monkeypatch):

    app = app_with_stream()
    runtime = SimpleNamespace(
        running=True,
        foreground=False,
        start=AsyncMock(),
        stop=AsyncMock(),
        standby=AsyncMock(),
    )
    runtime.snapshot = lambda: {"running": True, "foreground": False}
    app.state.voice_runtime = runtime
    tts_load = AsyncMock(return_value=None)
    monkeypatch.setattr("openjarvis.server.api_routes._resolve_tts_backend", tts_load)
    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    save_preference(
        enabled=True, options=StartVoiceRequest(speak=False).model_dump(mode="json")
    )
    await _start_voice(StartVoiceRequest(speak=False, silence_ms=2000), request)
    runtime.standby.assert_awaited_once()
    tts_load.assert_not_awaited()  # Playback off cannot cause a slow voice load.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        assert (await client.post("/v1/voice/standby")).status_code == 200
        assert load_preference().enabled
        runtime.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_saved_options_are_visible_and_never_acquire_microphone(
    monkeypatch,
):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    app.state.speech_backend = MagicMock()
    save_preference(enabled=True, options={"language": "fr"})
    start = AsyncMock()
    monkeypatch.setattr(voice_routes, "_start_voice", start)
    await restore_voice(app)
    assert "Invalid saved voice settings" in app.state.voice_restore_error
    start.assert_not_awaited()
    preference_path().write_text(
        json.dumps({"version": 1, "enabled": "false"}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_preference()


@pytest.mark.asyncio
async def test_start_saves_only_successful_options_and_stop_still_works_if_save_fails(
    monkeypatch,
):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    monkeypatch.setattr(voice_routes, "_start_voice", fake_start(app))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        response = await client.post(
            "/v1/voice/start", json={"language": "en", "speak": False}
        )
        assert (
            response.status_code == 200
            and load_preference().options["language"] == "en"
        )

        def fail_save(**kwargs):
            raise PermissionError("read only")

        monkeypatch.setattr("openjarvis.speech.preferences.save_preference", fail_save)
        response = await client.post("/v1/voice/stop")
        assert response.status_code == 507 and not app.state.voice_runtime.running
        assert app.state.voice_desired_enabled is False


@pytest.mark.asyncio
async def test_supervisor_keeps_live_conversation_and_recovers_capture_fault(
    monkeypatch,
):
    from openjarvis.server import voice_routes

    app = app_with_stream()
    app.state.speech_backend = MagicMock()
    save_preference(
        enabled=True, options=StartVoiceRequest(speak=False).model_dump(mode="json")
    )
    start = AsyncMock(side_effect=fake_start(app))
    monkeypatch.setattr(voice_routes, "_start_voice", start)
    async with app.router.lifespan_context(app):
        await wait_until_standby(app)
        original = app.state.voice_runtime
        original.foreground = True
        await asyncio.sleep(1.1)
        assert app.state.voice_runtime is original and start.await_count == 1
        assert original.foreground  # A live conversation must not be reset.
        original.running = False  # Authoritative capture-error state.
        async with asyncio.timeout(2):
            while start.await_count < 2:
                await asyncio.sleep(0.01)
        await wait_until_standby(app)
        assert app.state.voice_runtime is not original
        assert app.state.voice_desired_enabled is True
