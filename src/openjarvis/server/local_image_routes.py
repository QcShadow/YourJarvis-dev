"""Serve generated images from a fixed directory through the Jarvis origin."""

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from openjarvis.core.paths import get_config_dir

router = APIRouter(prefix="/v1/local-images", tags=["local-images"])


@router.get("/{filename}")
def get_image(filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.png", filename):
        raise HTTPException(status_code=404, detail="Image not found")
    path = get_config_dir() / "workspace/generated-images" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")
