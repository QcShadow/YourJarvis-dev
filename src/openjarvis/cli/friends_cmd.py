"""Explicit opt-in friends hosting, independent of the personal server."""

from __future__ import annotations

import click

from openjarvis.core.paths import get_config_dir


@click.group()
def friends():
    """Share model inference with complete clients through an isolated gateway."""


@friends.command("invite")
@click.argument("name")
def invite(name):
    """Create one member token; show it once, store only its hash."""
    from openjarvis.server.friends import invite_member

    try:
        token = invite_member(get_config_dir() / "friends-members.json", name)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Invitation for {name} (copy this token; it cannot be recovered):")
    click.echo(token)


@friends.command("revoke")
@click.argument("name")
def revoke(name):
    """Revoke a friend's token for subsequent requests."""
    from openjarvis.security.file_utils import secure_write_json
    from openjarvis.server.friends import load_members

    path = get_config_dir() / "friends-members.json"
    data = load_members(path)
    if name not in data:
        raise click.ClickException("Unknown member.")
    del data[name]
    secure_write_json(path, data)
    click.echo(f"Revoked {name}. An already-running response may finish.")


@friends.command("list")
def list_friends():
    """List member names without revealing any token or digest."""
    from openjarvis.server.friends import load_members

    for name in load_members(get_config_dir() / "friends-members.json"):
        click.echo(name)


@friends.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8001, type=click.IntRange(1, 65535))
@click.option(
    "--model", default="", help="Host-selected model; clients cannot override it."
)
@click.option("--max-waiting", default=4, type=click.IntRange(0, 20))
def serve_friends(host, port, model, max_waiting):
    """Serve inference; client-side agents execute their own tools and memory."""
    import uvicorn

    from openjarvis.core.config import load_config
    from openjarvis.core.credentials import inject_credentials
    from openjarvis.engine._discovery import _make_engine
    from openjarvis.server.friends import create_friends_app

    inject_credentials()
    cfg = load_config()
    engine = _make_engine(cfg.engine.default, cfg)
    try:
        app = create_friends_app(
            engine,
            model=model or cfg.intelligence.default_model,
            members_path=get_config_dir() / "friends-members.json",
            max_waiting=max_waiting,
            num_ctx=cfg.engine.ollama.num_ctx or 16384,
        )
    except (ValueError, OSError) as exc:
        engine.close()
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"JARVIS Link inference: http://{host}:{port}/v1 (no host files, tools or memory)"
    )
    uvicorn.run(app, host=host, port=port, access_log=False)
