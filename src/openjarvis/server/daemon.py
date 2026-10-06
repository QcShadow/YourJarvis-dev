"""Register daemon state only after Uvicorn has opened its listening socket."""

from __future__ import annotations

import os
import socket
from typing import Any

import uvicorn

from openjarvis.cli.daemon_cmd import clear_server_state, record_server_state


class DaemonServer(uvicorn.Server):
    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if not self.started:
            return
        listener = next(
            sock for server in self.servers for sock in (server.sockets or [])
        )
        host, port = listener.getsockname()[:2]
        try:
            record_server_state(os.getpid(), host, port)
        except Exception:
            # A second supervised server must not take over an existing live
            # daemon's entry. Close this listener and its application cleanly.
            await self.shutdown(sockets=sockets)
            raise


def run_server(app: Any, *, host: str, port: int, log_level: str = "info") -> None:
    identity = os.environ.get("JARVIS_DESKTOP_INSTANCE")
    if identity:
        app = DesktopIdentity(app, identity)
    server = DaemonServer(
        uvicorn.Config(app, host=host, port=port, log_level=log_level)
    )
    try:
        server.run()
    finally:
        # Includes startup failure: remove a parent-created pending entry, but
        # never an entry belonging to a different server process.
        clear_server_state(os.getpid())


class DesktopIdentity:
    """Prove that the responding backend belongs to this desktop launch."""

    def __init__(self, app: Any, identity: str) -> None:
        self.app = app
        self.identity = identity.encode("ascii")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def tagged(message: Any) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [
                    *message.get("headers", []),
                    (b"x-jarvis-instance", self.identity),
                ]}
            await send(message)

        await self.app(scope, receive, tagged)
