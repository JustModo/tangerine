from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.shared.preferences import PREFERENCES, get_preferences, set_preference

router = APIRouter(prefix="/settings", tags=["settings"])


class PatchSettingsBody(BaseModel):
    model_config = {"extra": "allow"}


async def _current_shape() -> dict[str, dict[str, object]]:
    values = await get_preferences()
    return {
        key: {"value": values[key], "options": definition["options"]}
        for key, definition in PREFERENCES.items()
    }


@router.get("")
async def get_settings() -> dict[str, dict[str, object]]:
    return await _current_shape()


@router.patch("")
async def patch_settings(body: PatchSettingsBody) -> dict[str, dict[str, object]]:
    for key, value in body.model_dump().items():
        try:
            await set_preference(key, value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _current_shape()
