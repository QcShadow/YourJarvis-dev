"""Recover opted-in wake listening without depending on an open web page."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, Request

from openjarvis.speech.preferences import load_preference

logger = logging.getLogger(__name__)


async def cancel_restore(app):
    task = getattr(app.state, "voice_restore_task", None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        if not task.cancelling():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def restore_voice(app):
    from openjarvis.server.voice_routes import (
        StartVoiceRequest,
        _control_lock,
        _start_voice,
    )

    request = Request(
        {"type": "http", "app": app, "headers": [], "client": ("127.0.0.1", 0)}
    )
    delay = 1
    while not getattr(app.state, "_managed_runtime_stopping", False):
        try:
            async with _control_lock(request):
                saved = load_preference()
                app.state.voice_desired_enabled = saved.enabled if saved else None
                if saved is None or not saved.enabled:
                    return
                if app.state.speech_backend is None:
                    raise RuntimeError(
                        "Saved voice is enabled but speech recognition "
                        "is not configured"
                    )
                body = StartVoiceRequest.model_validate(saved.options)
                runtime = getattr(app.state, "voice_runtime", None)
                if runtime is None or not runtime.running:
                    await _start_voice(body, request)
                    # No stale session, no unsolicited speech, no command replay.
                    await app.state.voice_runtime.standby()
                    logger.info("Restored opted-in microphone in wake-word standby")
                # A live conversation/standby stays untouched. Keep watching
                # the actual capture state, not just whether a page is open.
                app.state.voice_restore_error = ""
                delay = 1
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except (ValueError, TypeError) as exc:
            app.state.voice_restore_error = f"Invalid saved voice settings: {exc}"
            logger.warning("Voice restoration rejected invalid saved settings")
            return
        except HTTPException as exc:
            if exc.status_code == 422:
                app.state.voice_restore_error = "Invalid saved voice profile: " + str(
                    exc.detail
                )
                logger.warning("Voice restoration rejected invalid profile")
                return
            app.state.voice_restore_error = f"Voice recovery is waiting: {exc.detail}"
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)
        except Exception as exc:
            app.state.voice_restore_error = f"Voice recovery is waiting: {exc}"
            logger.warning("Voice restoration not ready; retry in %s seconds", delay)
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)


def ensure_restore(app):
    task = getattr(app.state, "voice_restore_task", None)
    if task is None or task.done():
        app.state.voice_restore_task = asyncio.create_task(
            restore_voice(app), name="jarvis-voice-restore"
        )


def register_voice_restore(app):
    app.state.voice_desired_enabled = None
    app.state.voice_restore_error = ""

    @app.on_event("startup")
    async def start_restore():
        # Missing/disabled/corrupt preferences do not acquire the microphone.
        try:
            saved = load_preference()
            app.state.voice_desired_enabled = saved.enabled if saved else None
        except (ValueError, OSError) as exc:
            app.state.voice_restore_error = f"Cannot read saved voice settings: {exc}"
            return
        if saved is not None and saved.enabled:
            ensure_restore(app)
