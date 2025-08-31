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
TMP_DIR = "/app/static/tmp"
os.makedirs(STATIC_RECEIPT_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

@router.post("/process-check")
async def process_check(payload: PhotoPayload):
    logger.info("📥 [process-check] file from user_id=%s: %s", payload.user_id, payload.file_url)

    async with httpx.AsyncClient() as client:
        resp = await client.get(payload.file_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Не удалось скачать изображение")
        content_type = resp.headers.get("Content-Type", "").lower()
        if "image" not in content_type and "octet-stream" not in content_type:
            raise HTTPException(status_code=400, detail=f"Некорректный тип данных: {content_type}")
        image_bytes = resp.content

    # сохраняем во временную папку (НЕ публичную)
    tmp_name = f"user_{payload.user_id}_{int(datetime.utcnow().timestamp())}.jpg"
    tmp_path = os.path.join(TMP_DIR, tmp_name)
    with open(tmp_path, "wb") as f:
        f.write(image_bytes)
    logger.info("💾 [process-check] temp saved: %s", tmp_path)


    raw = await analyze_receipt_from_bytes(image_bytes)

    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Ответ GPT не является корректным JSON")
    else:
        parsed = raw

    # НИКАКОГО image_url тут — ждём подтверждения
    parsed.pop("image_url", None)

    last_check_store[payload.user_id] = {
        "receipt": parsed,
        "tmp_name": tmp_name,
        "tmp_path": tmp_path,
    }

    logger.info("✅ [process-check] parsed & staged in memory for user_id=%s", payload.user_id)
    return {"result": parsed}
