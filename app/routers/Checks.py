from __future__ import annotations

import os
import shutil
from fastapi import APIRouter, Query, HTTPException, Depends, Header
from datetime import date, datetime, timedelta

import logging
from app.models.db.product import ProductDB
from app.models.saved_check import SaveReceiptPayload
from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.users import UserDB
from app.services.GPT import analyze_receipt_from_bytes, last_check_store
from app.services.jwt import verify_access_token
from app.deps.auth import get_current_user

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from sqlalchemy import select, and_, func

router = APIRouter()
STATIC_RECEIPT_DIR = "/app/static/receipts"
os.makedirs(STATIC_RECEIPT_DIR, exist_ok=True)
logger = logging.getLogger(__name__)
BASE_URL = os.getenv("BASE_URL", "https://mixfom2025.fvds.ru")


def _get_full_image_url(image_url: str) -> str:
    if not image_url:
        return image_url

    if image_url.startswith(('http://', 'https://')):
        return image_url

    if not image_url.startswith('/'):
        image_url = '/' + image_url

    return f"{BASE_URL}{image_url}"



@router.get("/last-check")
async def get_last_check(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Последний распознанный чек (staged) + список сохранённых чеков — доступ только по JWT."""
    user_id = int(user["sub"])

    # Последний чек из памяти (staged)
    last_check = last_check_store.get(user_id)

    # Если нет в памяти — попробуем найти последний сохранённый в БД (опционально)
    if not last_check:
        result = await db.execute(
            select(ReceiptDB).where(ReceiptDB.user_id == user_id).order_by(ReceiptDB.id.desc()).limit(1)
        )
        last_check = result.scalar()

    # Все сохранённые чеки пользователя
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
            "image_url": _get_full_image_url(receipt.image_url),
            "items": [item.__dict__ for item in items]
        })

    return {
        "last_check": last_check,
        "saved_checks": response
    }


@router.post("/save-check")
async def save_check(
    payload: SaveReceiptPayload,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Сохранение чека:
    - боту Bearer не нужен (сервер→сервер).
    - если пришёл Bearer, жёстко сверяем user_id с JWT.sub и не даём подменять.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        p = verify_access_token(token)
        if not p:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        jwt_uid = int(p["sub"])
        if payload.user_id and payload.user_id != jwt_uid:
            raise HTTPException(status_code=403, detail="user_id mismatch")
        payload.user_id = jwt_uid

    # Получаем временные данные
    staged = last_check_store.get(payload.user_id)
    image_url = payload.image_url

    # Перемещаем файл только при сохранении
    if staged and "tmp_path" in staged:
        tmp_path = staged["tmp_path"]
        if os.path.exists(tmp_path):
            filename = f"receipt_{payload.user_id}_{int(datetime.utcnow().timestamp())}.jpg"
            dest_path = os.path.join(STATIC_RECEIPT_DIR, filename)
            try:
                shutil.move(tmp_path, dest_path)
                image_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"
                if payload.user_id in last_check_store:
                    last_check_store[payload.user_id]["image_filename"] = filename
                    last_check_store[payload.user_id]["image_url"] = image_url
                    last_check_store[payload.user_id].pop("tmp_path", None)
            except Exception as e:
                logger.error(f"Ошибка перемещения файла: {e}")
                image_url = f"/static/tmp/{staged['tmp_name']}"
        else:
            if "image_filename" in staged:
                image_url = f"/static/receipts/{staged['image_filename']}"
            else:
                image_url = f"/static/tmp/{staged['tmp_name']}"

    # Создаём чек в БД
    receipt = ReceiptDB(
        user_id=payload.user_id,
        store=payload.store,
        date=payload.date,
        time=payload.time or "",
        total=payload.total,
        currency=payload.currency,
        image_url=image_url,
    )
    db.add(receipt)
    await db.flush()

    for item in payload.items:
        normalized_name = item.name.strip().lower()
        result = await db.execute(select(ProductDB).where(ProductDB.name.ilike(normalized_name)))
        product = result.scalar()
        if not product:
            product = ProductDB(
                name=item.name.strip(),
                category=item.category,
                category_id=item.category_id,
                subcategory=item.subcategory,
                subcategory_id=item.subcategory_id,
            )
            db.add(product)
            await db.flush()
        db.add(ReceiptItemDB(receipt_id=receipt.id, product_id=product.id, price=item.price))

    await db.commit()
    return {"status": "ok", "image_url": image_url}

@router.get("/edit-check")
async def edit_check(
    user=Depends(get_current_user)
):
    """Редактирование последнего распознанного (staged) — только по JWT."""
    user_id = int(user["sub"])
    logger.info("📥 [edit-check] Запрос от user_id=%s", user_id)

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
async def edit_saved_check(
    id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Редактирование СХРАНЁННОГО чека — только владелец (JWT.sub)."""
    user_id = int(user["sub"])

    # ВАЖНО: проверяем, что чек принадлежит текущему пользователю
    result = await db.execute(
        select(ReceiptDB).where(
            ReceiptDB.id == id,
            ReceiptDB.user_id == user_id
        )
    )
    receipt = result.scalar()
    if not receipt:
        # 404, чтобы не раскрывать наличие чужих записей
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
        "image_url": _get_full_image_url(receipt.image_url),
        "items": [item.__dict__ for item in items]
    }


@router.get("/saved-checks")
async def get_saved_checks(
    period: str = Query("month", pattern="^(day|week|month|year)$"),
    full: bool = Query(False, description="false — короткий вид, true — полный"),
    product_id: Optional[int] = Query(None, description="Фильтр: только чеки с этим product_id"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Список сохранённых чеков за период — доступ только по JWT."""
    user_id = int(user["sub"])

    # --- границы периода по дате СОХРАНЕНИЯ ---
    today = date.today()
    if period == "day":
        start = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = date(today.year, today.month, 1)
    elif period == "year":
        start = date(today.year, 1, 1)
    else:
        start = date(today.year, today.month, 1)

    start_date = start
    end_date = today

    # --- база чеков за период (по created_at) ---
    q = (
        select(ReceiptDB)
        .where(
            and_(
                ReceiptDB.user_id == user_id,
                func.date(ReceiptDB.created_at).between(start, today)
            )
        )
        .order_by(ReceiptDB.created_at.desc(), ReceiptDB.id.desc())
    )

    if product_id is not None:
        q = (
            q.join(ReceiptItemDB, ReceiptItemDB.receipt_id == ReceiptDB.id)
            .where(ReceiptItemDB.product_id == product_id)
            .distinct()
        )

    result = await db.execute(q)
    receipts = result.scalars().all()

    if not full:
        data = [
            {
                "id": r.id,
                "store": r.store,
                "date": r.date,
                "time": r.time,
                "total": r.total,
                "currency": r.currency,
                "image_url": _get_full_image_url(r.image_url),
                "saved_at": (r.created_at.isoformat() if r.created_at else None),
            }
            for r in receipts
        ]
        return {
            "period": period,
            "from_date": start.isoformat(),
            "to_date": today.isoformat(),
            "filter_product_id": product_id,
            "saved_checks": data,
            "count": len(data),
            "total_amount": round(sum((r.total or 0) for r in receipts), 2),
        }

    # полный ответ с товарами
    receipt_ids = [r.id for r in receipts]
    items_by_receipt: dict[int, list[dict]] = {rid: [] for rid in receipt_ids}

    if receipt_ids:
        items_q = (
            select(
                ReceiptItemDB.receipt_id,
                ReceiptItemDB.product_id,
                ReceiptItemDB.price,
                ProductDB.name,
                ProductDB.category,
                ProductDB.category_id,
                ProductDB.subcategory,
                ProductDB.subcategory_id,
            )
            .select_from(ReceiptItemDB)
            .join(ProductDB, ProductDB.id == ReceiptItemDB.product_id, isouter=True)
            .where(ReceiptItemDB.receipt_id.in_(receipt_ids))
            .order_by(ReceiptItemDB.id.asc())
        )
        if product_id is not None:
            items_q = items_q.where(ReceiptItemDB.product_id == product_id)

        ir = await db.execute(items_q)
        for rid, pid, price, pname, pcat, pcat_id, psub, psub_id in ir.all():
            items_by_receipt[rid].append(
                {
                    "product_id": pid,
                    "name": pname,
                    "price": price,
                    "category": pcat,
                    "category_id": pcat_id,
                    "subcategory": psub,
                    "subcategory_id": psub_id,
                }
            )

    data = [
        {
            "id": r.id,
            "store": r.store,
            "date": r.date,
            "time": r.time,
            "total": r.total,
            "currency": r.currency,
            "image_url": _get_full_image_url(r.image_url),
            "saved_at": (r.created_at.isoformat() if r.created_at else None),
            "items": items_by_receipt.get(r.id, []),
        }
        for r in receipts
    ]

    return {
        "period": period,
        "from_date": start.isoformat(),
        "to_date": today.isoformat(),
        "filter_product_id": product_id,
        "saved_checks": data,
        "count": len(data),
        "total_amount": round(sum((r.total or 0) for r in receipts), 2),
    }



