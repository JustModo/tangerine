import asyncio

from fastapi import APIRouter, HTTPException
from google import genai
from google.genai.errors import ClientError
from pydantic import BaseModel, Field

from app.shared.secrets import clear_gemini_api_key, gemini_key_status, set_gemini_api_key

router = APIRouter(prefix="/setup", tags=["setup"])

_VALIDATION_TIMEOUT_S = 15.0


class GeminiKeyBody(BaseModel):
    api_key: str = Field(min_length=1)


async def validate_gemini_key(api_key: str) -> None:
    try:
        async with asyncio.timeout(_VALIDATION_TIMEOUT_S):
            await genai.Client(api_key=api_key).aio.models.list()
    except TimeoutError:
        raise ValueError("Timed out reaching Gemini. Check the network and try again.") from None
    except ClientError as exc:
        raise ValueError("Gemini rejected that key.") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Couldn't reach Gemini. Check the network and try again.") from exc


@router.get("/gemini-key")
async def get_gemini_key() -> dict:
    return await gemini_key_status()


@router.put("/gemini-key")
async def put_gemini_key(body: GeminiKeyBody) -> dict:
    try:
        await validate_gemini_key(body.api_key.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await set_gemini_api_key(body.api_key.strip())
    return await gemini_key_status()


@router.delete("/gemini-key")
async def delete_gemini_key() -> dict:
    await clear_gemini_api_key()
    return await gemini_key_status()
