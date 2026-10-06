"""Small, separate friends gateway: inference only, no owner app/state/tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from openjarvis.core.types import Message, Role
from openjarvis.security.file_utils import secure_write_json

logger = logging.getLogger(__name__)
CHAT_PROMPT = (
    "你是 JARVIS，朋友们共用的聊天助手。回答友好、自然、简洁，默认用简体中文。"
    "你只能进行文字聊天，没有文件、桌面、浏览器、命令执行或私人记忆访问能力。"
    "不要声称已经完成任何现实操作。"
)


def load_members(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(
        not isinstance(name, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        for name, digest in data.items()
    ):
        raise ValueError("Invalid friends member file; expected name -> SHA256 digest.")
    return data


def invite_member(path: Path, name: str) -> str:
    name = name.strip()
    if not name or len(name) > 64 or any(ord(c) < 32 for c in name):
        raise ValueError("Member name must be 1-64 visible characters.")
    members = load_members(path)
    if name in members:
        raise ValueError(
            "Member already exists; revoke the old token before inviting again."
        )
    token = "jf_" + secrets.token_urlsafe(32)
    members[name] = hashlib.sha256(token.encode()).hexdigest()
    secure_write_json(path, members)
    return token


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class FriendsChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[HistoryMessage] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_history(self):
        if self.messages[-1].role != "user":
            raise ValueError("Last message must be from the user.")
        if sum(len(m.content) for m in self.messages) > 8000:
            raise ValueError("History is too long; start a new conversation.")
        return self


class BodyLimit:
    """Bound bytes before JSON/Pydantic parsing, including chunked requests."""

    def __init__(self, app, maximum=65536):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            part = await receive()
            if part["type"] == "http.disconnect":
                return
            size += len(part.get("body", b""))
            maximum = (
                2 * 1024 * 1024
                if scope["path"] == "/v1/chat/completions"
                else self.maximum
            )
            if size > maximum:
                response = JSONResponse(
                    {"detail": "Request too large"}, status_code=413
                )
                return await response(scope, receive, send)
            chunks.append(part)
            if not part.get("more_body", False):
                break
        replay = iter(chunks)

        async def bounded_receive():
            return next(replay, None) or await receive()

        await self.app(scope, bounded_receive, send)


class AdmissionStreamingResponse(StreamingResponse):
    """Release admission even if the client disconnects before iteration."""

    def __init__(self, *args, release, **kwargs):
        super().__init__(*args, **kwargs)
        self._release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


def create_friends_app(
    engine,
    *,
    model: str,
    members_path: Path,
    max_waiting: int = 4,
    wait_seconds: float = 60,
    requests_per_minute: int = 60,
    inference_seconds: float = 180,
    num_ctx: int = 4096,
) -> FastAPI:
    if not model or max_waiting < 0 or wait_seconds <= 0:
        raise ValueError("Invalid friends gateway settings.")
    members = load_members(members_path)
    if not members:
        raise ValueError("Invite at least one friend before starting the gateway.")
    gate = asyncio.Semaphore(1)
    in_flight: set[str] = set()
    rates: dict[str, deque] = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.close()

    app = FastAPI(
        title="JARVIS Link Gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'"
        )
        return response

    async def authenticated(request: Request):
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 256:
            raise HTTPException(401, "Enter your invitation token.")
        digest = hashlib.sha256(token.encode()).hexdigest()
        # Reload on each request so revoke takes effect without a restart.
        current = load_members(members_path)
        for name, expected in current.items():
            if secrets.compare_digest(digest, expected):
                return name
        raise HTTPException(401, "Invalid or revoked invitation token.")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/friends/config")
    async def config(member: str = Depends(authenticated)):
        return {
            "member": member,
            "model": model,
            "max_messages": 12,
            "max_history_chars": 8000,
            "voice_available": False,
        }

    async def admit(member: str):
        now = time.monotonic()
        recent = rates[member]
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= requests_per_minute:
            raise HTTPException(429, "Too many requests; retry in a minute.")
        if member in in_flight:
            raise HTTPException(429, "Your previous request is still running.")
        if len(in_flight) >= max_waiting + 1:
            raise HTTPException(503, "The host is busy; retry shortly.")
        in_flight.add(member)
        recent.append(now)
        acquired = False
        try:
            await asyncio.wait_for(gate.acquire(), timeout=wait_seconds)
            acquired = True
        except asyncio.TimeoutError as exc:
            in_flight.discard(member)
            raise HTTPException(503, "Queue timed out; retry shortly.") from exc
        except BaseException:
            in_flight.discard(member)
            if acquired:
                gate.release()
            raise

        released = False

        def release_slot():
            nonlocal released
            if not released:
                released = True
                gate.release()
                in_flight.discard(member)

        return release_slot

    from openjarvis.server.inference_gateway import install_inference_routes

    install_inference_routes(
        app,
        engine=engine,
        model=model,
        authenticated=authenticated,
        admit=admit,
        response_class=AdmissionStreamingResponse,
        inference_seconds=inference_seconds,
        num_ctx=num_ctx,
    )

    @app.post("/api/friends/chat")
    async def chat(
        body: FriendsChat, request: Request, member: str = Depends(authenticated)
    ):
        release_slot = await admit(member)
        messages = [Message(role=Role.SYSTEM, content=CHAT_PROMPT)] + [
            Message(role=Role(item.role), content=item.content)
            for item in body.messages
        ]

        async def stream():
            upstream = None
            try:
                # A single slot remains occupied until the upstream stream is
                # closed. Disconnect/cancellation cannot leave a stale member.
                upstream = engine.stream(
                    messages,
                    model=model,
                    temperature=0.5,
                    max_tokens=512,
                    num_ctx=num_ctx,
                )
                deadline = time.monotonic() + inference_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        token = await asyncio.wait_for(anext(upstream), remaining)
                    except StopAsyncIteration:
                        break
                    if await request.is_disconnected():
                        return
                    yield (
                        "data: "
                        + json.dumps({"content": token}, ensure_ascii=False)
                        + "\n\n"
                    )
                yield "data: [DONE]\n\n"
            except Exception:
                # Never send upstream bodies, keys or private URLs to friends.
                logger.warning("Friends inference failed")
                yield 'data: {"error":"模型暂时不可用或超时，请稍后重试。"}\n\n'
            finally:
                try:
                    if upstream is not None:
                        await upstream.aclose()
                finally:
                    release_slot()

        return AdmissionStreamingResponse(
            stream(),
            release=release_slot,
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    static = Path(__file__).parent / "friends_static"

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/friends.js")
    async def javascript():
        return FileResponse(static / "friends.js", media_type="text/javascript")

    @app.get("/friends.css")
    async def stylesheet():
        return FileResponse(static / "friends.css", media_type="text/css")

    return app
