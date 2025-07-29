import httpx
from fastapi import APIRouter, Query, HTTPException, Depends
from app.models.saved_check import SaveReceiptPayload
from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.checkPhoto import PhotoPayload
from app.services.GPT import analyze_receipt_from_bytes, last_check_store
from sqlalchemy.ext.asyncio import AsyncSession
router = APIRouter()

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
    await db.flush()  # чтобы получить ID перед вставкой items

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
