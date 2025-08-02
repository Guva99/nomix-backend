import json
import os
import uuid
from datetime import datetime
import httpx
from fastapi import APIRouter, Query, HTTPException, Depends

import logging
from app.models.saved_check import SaveReceiptPayload
from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.checkPhoto import PhotoPayload
from app.models.users import UserDB
from app.services.GPT import analyze_receipt_from_bytes, last_check_store
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
router = APIRouter()
STATIC_RECEIPT_DIR = "app/static/receipts"
os.makedirs(STATIC_RECEIPT_DIR, exist_ok=True)
logger = logging.getLogger(__name__)

@router.post("/process-check")
async def process_check(payload: PhotoPayload):
    async with httpx.AsyncClient() as client:
        resp = await client.get(payload.file_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Не удалось скачать изображение")

        content_type = resp.headers.get("Content-Type", "").lower()
        if "image" not in content_type and "octet-stream" not in content_type:
            raise HTTPException(status_code=400, detail=f"Некорректный тип данных: {content_type}")

        image_bytes = resp.content

    # Сохраняем изображение
    filename = f"user_{payload.user_id}_{datetime.utcnow().timestamp():.0f}.jpg"
    filepath = os.path.join(STATIC_RECEIPT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)

    public_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"

    # Анализируем чек
    raw_result = await analyze_receipt_from_bytes(image_bytes)

    if isinstance(raw_result, str):
        cleaned = raw_result.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("❌ Ошибка парсинга JSON от GPT: %s", e)
            logger.error("📦 Ответ от GPT:\n%s", raw_result)
            raise HTTPException(status_code=500, detail="Ответ GPT не является корректным JSON")
    else:
        result = raw_result


    result["image_url"] = public_url

    # Сохраняем результат по user_id
    last_check_store[payload.user_id] = result

    return {"result": result}

