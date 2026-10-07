"""Local voice-library management; remote gateways do not share this library."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from openjarvis.server.voice_routes import _require_local
from openjarvis.speech import voice_packs

router = APIRouter(prefix="/v1/speech/packs", tags=["voice-packs"])


def require_local(request):
    _require_local(request)
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "音色库管理仅支持本机应用")


@router.get("")
async def list_packs(request: Request):
    require_local(request)
    return {"packs": await asyncio.to_thread(voice_packs.catalog)}


@router.post("/import", status_code=201)
async def import_pack(
    request: Request,
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    transcript: str = Form(""),
    reference_language: str = Form("zh"),
    speaker_id: int = Form(0),
):
    require_local(request)
    if len(files) > 3:
        raise HTTPException(413, "一次最多选择三个文件")
    data = []
    total = 0
    try:
        for upload in files:
            chunks = []
            file_total = 0
            lower = (upload.filename or "").lower()
            limit = (
                voice_packs.MAX_AUDIO
                if lower.endswith(".wav")
                else 256 * 1024
                if lower.endswith((".txt", ".json"))
                else voice_packs.MAX_UPLOAD
            )
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                file_total += len(chunk)
                if file_total > limit:
                    raise HTTPException(413, "音色文件超过此格式的大小限制")
                if total > voice_packs.MAX_UPLOAD:
                    raise HTTPException(413, "上传总大小不能超过 256 MB")
                chunks.append(chunk)
            data.append((upload.filename or "", b"".join(chunks)))
        result = await asyncio.to_thread(
            voice_packs.install,
            data,
            name=name,
            transcript=transcript,
            reference_language=reference_language,
            speaker_id=speaker_id,
        )
        return voice_packs.public_profile(result)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.patch("/{pack_id}")
async def rename_pack(pack_id: str, body: RenameRequest, request: Request):
    require_local(request)
    try:
        return await asyncio.to_thread(voice_packs.rename, pack_id, body.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{pack_id}/export")
async def export_pack(pack_id: str, request: Request):
    require_local(request)
    try:
        data = await asyncio.to_thread(voice_packs.export, pack_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{pack_id}.jvoice"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{pack_id}", status_code=204)
async def delete_pack(pack_id: str, request: Request):
    require_local(request)
    from openjarvis.speech.preferences import load_preference

    saved = load_preference()
    # Stored background settings must remain valid even while listening is off.
    if saved and saved.options and saved.options.get("voice_profile") == pack_id:
        raise HTTPException(409, "请先在语音设置中切换后台使用的音色，再删除")
    runtime = getattr(request.app.state, "voice_runtime", None)
    if (
        runtime
        and runtime.running
        and getattr(getattr(runtime, "options", None), "voice_profile", "") == pack_id
    ):
        raise HTTPException(409, "后台正在使用此音色，请先切换")
    tasks = getattr(request.app.state, "voice_profile_loads", {})
    if any(
        isinstance(key, tuple) and key[1] == pack_id and not task.done()
        for key, task in tasks.items()
    ):
        raise HTTPException(409, "音色正在加载，请稍后再删除")
    try:
        await asyncio.to_thread(voice_packs.delete, pack_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    for key in list(tasks):
        if isinstance(key, tuple) and key[1] == pack_id:
            task = tasks.pop(key)
            if task.done() and not task.cancelled() and task.exception() is None:
                await asyncio.to_thread(task.result().close)
    getattr(request.app.state, "voice_synthesizers", {}).pop(pack_id, None)
    return Response(status_code=204)
