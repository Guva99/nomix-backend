from fastapi.responses import StreamingResponse
import httpx
import os
from fastapi import APIRouter, HTTPException

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
router = APIRouter()

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
