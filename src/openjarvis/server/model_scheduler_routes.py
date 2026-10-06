"""Live local model scheduling status and resource settings."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.core.model_scheduler import save_settings, snapshot

router = APIRouter(prefix="/v1/model-scheduler", tags=["model-scheduler"])


class SettingsRequest(BaseModel):
    image_device: str = "auto"
    main_during_image: str = "cpu"
    voice_idle_seconds: int = Field(default=120, ge=0, le=1800)
    writer_idle_seconds: int = Field(default=120, ge=0, le=1800)
    cpu_image_idle_seconds: int = Field(default=120, ge=0, le=1800)
    voice_wait_seconds: int = Field(default=120, ge=0, le=1800)


@router.get("")
def status(request: Request):
    result = snapshot()
    manager = getattr(request.app.state, "agent_manager", None)
    result["agents"] = []
    if manager is not None:
        result["agents"] = [{"id": agent["id"], "name": agent["name"], "status": agent["status"],
                             "model": agent.get("config", {}).get("model", ""),
                             "activity": agent.get("current_activity", "")}
                            for agent in manager.list_agents()]
    return result


@router.put("/settings")
def update_settings(body: SettingsRequest):
    try:
        return save_settings(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
