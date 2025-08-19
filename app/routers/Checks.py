import os
from fastapi import APIRouter, Query, HTTPException, Depends

import logging
from app.models.saved_check import SaveReceiptPayload
from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.users import UserDB
from app.services.GPT import analyze_receipt_from_bytes, last_check_store
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

router = APIRouter()
STATIC_RECEIPT_DIR = "/app/static/receipts"
os.makedirs(STATIC_RECEIPT_DIR, exist_ok=True)
logger = logging.getLogger(__name__)


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

    if not last_check:  # Если нет в памяти, пытаемся найти в базе
        result = await db.execute(
            select(ReceiptDB).where(ReceiptDB.user_id == user_id).order_by(ReceiptDB.id.desc()).limit(1)
        )
        last_check = result.scalar()

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
        image_url=payload.image_url
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
    logger.info("📥 [edit-check] Запрос от user_id=%s", user_id)

    # Выводим содержимое хранилища на случай отладки
    if not last_check_store:
        logger.warning("⚠️ [edit-check] last_check_store пуст")
    else:
        logger.info("🗃 [edit-check] Ключи в last_check_store: %s", list(last_check_store.keys()))
        if user_id in last_check_store:
            logger.info("✅ [edit-check] Чек найден для user_id=%s", user_id)
        else:
            logger.warning("❌ [edit-check] Чек не найден для user_id=%s", user_id)

    if user_id not in last_check_store:
        raise HTTPException(status_code=404, detail="Чек для пользователя не найден")

    return last_check_store[user_id]

@router.get("/edit-saved-check")
async def edit_saved_check(id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(ReceiptDB).where(ReceiptDB.id == id))
    receipt = result.scalar()
    if not receipt:
        raise HTTPException(status_code=404, detail="Чек не найден")

    items_result = await db.execute(select(ReceiptItemDB).where(ReceiptItemDB.receipt_id == id))
    items = items_result.scalars().all()

    return {
        "id": receipt.id,
        "store": receipt.store,
        "date": receipt.date,
        "time": receipt.time,
        "total": receipt.total,
        "currency": receipt.currency,
        "image_url": receipt.image_url,
        "items": [item.__dict__ for item in items]
    }


@router.get("/saved-checks")
async def get_saved_checks(
    user_id: int = Query(...),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_items: bool = Query(False),
    db: AsyncSession = Depends(get_db_session),
):
    # вернуть только сохранённые чеки
    q = (
        select(ReceiptDB)
        .where(ReceiptDB.user_id == user_id)
        .order_by(ReceiptDB.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    receipts = result.scalars().all()

    data = []
    for r in receipts:
        row = {
            "id": r.id,
            "store": r.store,
            "date": r.date,
            "time": r.time,
            "total": r.total,
            "currency": r.currency,
            "image_url": r.image_url,
        }
        if include_items:
            items_result = await db.execute(
                select(ReceiptItemDB).where(ReceiptItemDB.receipt_id == r.id)
            )
            items = items_result.scalars().all()
            row["items"] = [
                {
                    "id": it.id,
                    "receipt_id": it.receipt_id,
                    "name": it.name,
                    "price": it.price,
                    "category": it.category,
                    "category_id": it.category_id,
                    "subcategory": it.subcategory,
                    "subcategory_id": it.subcategory_id,
                } for it in items
            ]
        data.append(row)

    return {"saved_checks": data, "limit": limit, "offset": offset}
