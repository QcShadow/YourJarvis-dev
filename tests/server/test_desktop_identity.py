import pytest

from openjarvis.server.daemon import DesktopIdentity


@pytest.mark.asyncio
async def test_desktop_identity_proves_launch_and_preserves_response():
    received = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"status":"ok"}'})

    async def send(message):
        received.append(message)

    await DesktopIdentity(app, "own-launch")({"type": "http"}, None, send)
    assert (b"x-jarvis-instance", b"own-launch") in received[0]["headers"]
    assert (b"content-type", b"application/json") in received[0]["headers"]
    assert received[1]["body"] == b'{"status":"ok"}'
