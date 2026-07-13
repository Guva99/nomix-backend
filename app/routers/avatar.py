from fastapi.responses import StreamingResponse
import httpx
from fastapi import APIRouter, HTTPException

from app.core.settings import settings

router = APIRouter()

TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

@router.get("/avatar/{file_path:path}")
async def proxy_telegram_avatar(file_path: str):
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Avatar not found")

    return StreamingResponse(
        iter([resp.content]),
        media_type="image/jpeg"
    )
