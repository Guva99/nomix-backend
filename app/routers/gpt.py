import json
import os
from datetime import datetime
import httpx
from fastapi import APIRouter, HTTPException

import logging
from app.models.checkPhoto import PhotoPayload
from app.services.GPT import analyze_receipt_from_bytes, last_check_store

router = APIRouter()
STATIC_RECEIPT_DIR = "/app/static/receipts"
os.makedirs(STATIC_RECEIPT_DIR, exist_ok=True)
logger = logging.getLogger(__name__)

@router.post("/process-check")
async def process_check(payload: PhotoPayload):
    logger.info("📥 [process-check] Получен файл от user_id=%s: %s", payload.user_id, payload.file_url)

    async with httpx.AsyncClient() as client:
        resp = await client.get(payload.file_url)
        if resp.status_code != 200:
            logger.error("❌ [process-check] Не удалось скачать изображение, статус: %s", resp.status_code)
            raise HTTPException(status_code=400, detail="Не удалось скачать изображение")

        content_type = resp.headers.get("Content-Type", "").lower()
        logger.info("🧾 [process-check] Тип контента: %s", content_type)
        if "image" not in content_type and "octet-stream" not in content_type:
            raise HTTPException(status_code=400, detail=f"Некорректный тип данных: {content_type}")

        image_bytes = resp.content

    filename = f"user_{payload.user_id}_{datetime.utcnow().timestamp():.0f}.jpg"
    filepath = os.path.join(STATIC_RECEIPT_DIR, filename)
    logger.info("💾 [process-check] Сохраняем чек в: %s", filepath)
    with open(filepath, "wb") as f:
        f.write(image_bytes)

    public_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"
    logger.info("🌐 [process-check] Публичная ссылка на изображение: %s", public_url)

    raw_result = await analyze_receipt_from_bytes(image_bytes)

    # Обработка результата от GPT
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
            logger.error("📦 Ответ от GPT:\n%s", raw_result[:1000])  # Логируем только первые 1000 символов
            raise HTTPException(status_code=500, detail="Ответ GPT не является корректным JSON")
    else:
        result = raw_result

    result["image_url"] = public_url
    last_check_store[payload.user_id] = result

    logger.info("✅ [process-check] Чек успешно проанализирован и сохранён во временное хранилище для user_id=%s", payload.user_id)

    return {"result": result}
