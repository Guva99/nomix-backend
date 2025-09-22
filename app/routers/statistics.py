from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.db.product import ProductDB
from app.models.Statistics import StatisticsResponse, Summary, CategoryStat, TopItem
from app.deps.auth import get_current_user  # <-- JWT

router = APIRouter()

def purchased_at_expr():
    return func.to_timestamp(
        func.concat(ReceiptDB.date, literal_column("' '"), func.coalesce(ReceiptDB.time, literal_column("'00:00'"))),
        literal_column("'YYYY-MM-DD HH24:MI'")
    )

@router.get("/statistics", response_model=StatisticsResponse, summary="Статистика расходов пользователя")
async def get_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),                      # <-- требуем JWT

    date_from: Optional[str] = Query(None, description="YYYY-MM-DD, включительно"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD, включительно"),
    include_top_items: bool = Query(True, description="Включить ТОП-товары"),
    top_items_limit: int    = Query(5, ge=1, le=50, description="Размер ТОП-списка"),
):
    # user_id только из токена
    uid = int(user["sub"])

    try:
        dt_to   = datetime.strptime(date_to,   "%Y-%m-%d") if date_to   else datetime.utcnow()
        dt_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else (dt_to - timedelta(days=30))
    except ValueError:
        raise HTTPException(status_code=422, detail="Неверный формат даты. Используйте YYYY-MM-DD.")

    dt_from_norm = dt_from.replace(hour=0, minute=0, second=0, microsecond=0)
    dt_to_inc    = dt_to.replace(hour=23, minute=59, second=59, microsecond=999999)
    purchased_ts = purchased_at_expr()

    # SUMMARY
    summary_q = (
        select(
            func.coalesce(func.sum(ReceiptDB.total), 0.0),
            func.count(ReceiptDB.id),
            func.coalesce(func.avg(ReceiptDB.total), 0.0),
            func.count(func.distinct(ReceiptDB.store)),
        )
        .where(
            (ReceiptDB.user_id == uid) &
            (purchased_ts >= dt_from_norm) &
            (purchased_ts <= dt_to_inc)
        )
    )
    total_spent, purchase_count, avg_ticket, unique_stores = (await db.execute(summary_q)).one()

    # BY CATEGORY
    cat_q = (
        select(
            ReceiptItemDB.category_id,
            ReceiptItemDB.category,
            func.coalesce(func.sum(ReceiptItemDB.price), 0.0).label("total_spent"),
            func.count(ReceiptItemDB.id).label("purchase_count"),
            func.coalesce(func.avg(ReceiptItemDB.price), 0.0).label("avg_item_price"),
        )
        .join(ReceiptDB, ReceiptDB.id == ReceiptItemDB.receipt_id)
        .where(
            (ReceiptDB.user_id == uid) &
            (purchased_ts >= dt_from_norm) &
            (purchased_ts <= dt_to_inc)
        )
        .group_by(ReceiptItemDB.category_id, ReceiptItemDB.category)
        .order_by(literal_column("total_spent").desc())
    )
    cat_rows = (await db.execute(cat_q)).all()
    by_category: List[CategoryStat] = [
        CategoryStat(
            category_id=int(r.category_id or 0),
            category=r.category,
            total_spent=float(r.total_spent or 0),
            purchase_count=int(r.purchase_count or 0),
            avg_item_price=float(r.avg_item_price or 0),
        )
        for r in cat_rows
    ]

    # TOP ITEMS (по ProductDB.name)
    top_items: List[TopItem] = []
    if include_top_items and top_items_limit > 0:
        top_q = (
            select(
                ProductDB.name.label("name"),
                func.coalesce(func.sum(ReceiptItemDB.price), 0.0).label("total_spent"),
                func.count(ReceiptItemDB.id).label("count"),
            )
            .join(ReceiptDB, ReceiptDB.id == ReceiptItemDB.receipt_id)
            .join(ProductDB, ProductDB.id == ReceiptItemDB.product_id, isouter=True)
            .where(
                (ReceiptDB.user_id == uid) &
                (purchased_ts >= dt_from_norm) &
                (purchased_ts <= dt_to_inc)
            )
            .group_by(ProductDB.name)
            .order_by(literal_column("total_spent").desc())
            .limit(top_items_limit)
        )
        for r in (await db.execute(top_q)).all():
            top_items.append(TopItem(name=r.name or "—", total_spent=float(r.total_spent or 0), count=int(r.count or 0)))

    return StatisticsResponse(
        user_id=uid,
        date_from=dt_from_norm.date().isoformat(),
        date_to=dt_to_inc.date().isoformat(),
        summary=Summary(
            total_spent=float(total_spent or 0),
            purchase_count=int(purchase_count or 0),
            avg_ticket=float(avg_ticket or 0),
            unique_stores=int(unique_stores or 0),
        ),
        by_category=by_category,
        top_items=top_items,
    )
