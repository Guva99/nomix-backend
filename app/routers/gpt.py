import httpx
from fastapi import APIRouter, Query, HTTPException
from app.models.saved_check import SaveReceiptPayload

from app.models.checkPhoto import PhotoPayload
from app.services.GPT import analyze_receipt_from_bytes, last_check_store
router = APIRouter()

@router.post("/api/process-check")
async def process_check(payload: PhotoPayload):
    async with httpx.AsyncClient() as client:
        resp = await client.get(payload.file_url)
        image_bytes = resp.content

    result = await analyze_receipt_from_bytes(image_bytes)

    # Сохраняем результат по user_id
    last_check_store[payload.user_id] = result

    return {"result": result}

@router.get("/api/last-check")
async def get_last_check(user_id: int = Query(...)):
    if user_id not in last_check_store:
        raise HTTPException(status_code=404, detail="Чек для пользователя не найден")
    return {"result": last_check_store[user_id]}

@router.post("/api/save-check")
async def save_check(payload: SaveReceiptPayload):
    # Тут будет логика сохранения в БД
    # Пример: await db.save_check(payload)
    print(f"Saving receipt for user {payload.user_id}: {payload.store}, {payload.total}")
    return {"status": "ok"}
