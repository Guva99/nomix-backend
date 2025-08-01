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
STATIC_RECEIPT_DIR = "static/receipts"
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

    try:
        result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except json.JSONDecodeError as e:
        logger.error("❌ Ошибка парсинга JSON от GPT: %s", e)
        logger.error("📦 Ответ от GPT:\n%s", raw_result)
        raise HTTPException(status_code=500, detail="Ответ GPT не является корректным JSON")


    result["image_url"] = public_url

    # Сохраняем результат по user_id
    last_check_store[payload.user_id] = result

    return {"result": result}

@router.get("/last-check")
async def get_last_check(
    user_id: int = Query(None),
    token: str = Query(None),
    db: AsyncSession = Depends(get_db_session)
):
    if not user_id and not token:
        raise HTTPException(status_code=400, detail="Нужно передать либо user_id, либо token")

    # Получаем user_id по токену
    if token and not user_id:
        result = await db.execute(select(UserDB).where(UserDB.token == token))
        user = result.scalar()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь по токену не найден")
        user_id = user.id

    # Получаем последний чек из памяти
    last_check = last_check_store.get(user_id)

    # Получаем все сохранённые чеки из базы
    result = await db.execute(
        select(ReceiptDB).where(ReceiptDB.user_id == user_id).order_by(ReceiptDB.id.desc())
    )
    receipts = result.scalars().all()

    response = []
    for receipt in receipts:
        item_result = await db.execute(
            select(ReceiptItemDB).where(ReceiptItemDB.receipt_id == receipt.id)
        )
        items = item_result.scalars().all()
        response.append({
            "id": receipt.id,
            "store": receipt.store,
            "date": receipt.date,
            "time": receipt.time,
            "total": receipt.total,
            "currency": receipt.currency,
            "image_url": receipt.image_url,
            "items": [item.__dict__ for item in items]
        })

    return {
        "last_check": last_check,
        "saved_checks": response
    }


@router.post("/save-check")
async def save_check(payload: SaveReceiptPayload, db: AsyncSession = Depends(get_db_session)):
    receipt = ReceiptDB(
        user_id=payload.user_id,
        store=payload.store,
        date=payload.date,
        time=payload.time or "",
        total=payload.total,
        currency=payload.currency,
    )

    db.add(receipt)
    await db.flush()

    for item in payload.items:
        db.add(ReceiptItemDB(
            receipt_id=receipt.id,
            name=item.name,
            price=item.price,
            category=item.category,
            category_id=item.category_id,
            subcategory=item.subcategory or "",
            subcategory_id=item.subcategory_id
        ))

    await db.commit()
    return {"status": "ok"}

@router.get("/edit-check")
async def edit_check(user_id: int = Query(...)):
    if user_id not in last_check_store:
        raise HTTPException(status_code=404, detail="Чек для пользователя не найден")
    return last_check_store[user_id]
