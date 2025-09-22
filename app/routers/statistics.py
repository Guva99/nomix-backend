# routers/statistics.py
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.models.db.product import ProductDB
from app.models.Statistics import StatisticsResponse, Summary, CategoryStat, TopItem
from app.deps.auth import get_current_user  # <-- JWT

router = APIRouter()

# ---------- helpers ----------

def purchased_at_expr():
    """
    Превращаем (date TEXT 'YYYY-MM-DD', time TEXT 'HH:MI'|NULL) в TIMESTAMP.
    Лучше в будущем завести отдельное поле `purchased_at TIMESTAMP` и индекс.
    """
    return func.to_timestamp(
        func.concat(
            ReceiptDB.date,
            literal_column("' '"),
            func.coalesce(ReceiptDB.time, literal_column("'00:00'"))
        ),
        literal_column("'YYYY-MM-DD HH24:MI'")
    )

def month_bounds(ym: str) -> Tuple[datetime, datetime]:
    """Вернёт (начало, конец_включительно) для месяца 'YYYY-MM'."""
    try:
        y, m = map(int, ym.split("-"))
        start = datetime(y, m, 1, 0, 0, 0, 0)
        last_day = calendar.monthrange(y, m)[1]
        end = datetime(y, m, last_day, 23, 59, 59, 999999)
        return start, end
    except Exception:
        raise HTTPException(status_code=422, detail="Неверный формат месяца. Используйте YYYY-MM.")

def prev_month_str(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    if m == 1:
        return f"{y-1}-12"
    return f"{y:04d}-{m-1:02d}"

# ---------- main statistics ----------

@router.get("/statistics", response_model=StatisticsResponse, summary="Статистика расходов пользователя")
async def get_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),  # <-- требуем JWT

    # старые параметры (обратная совместимость)
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD, включительно"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD, включительно"),

    # новые параметры: выбор месяцами
    month_from: Optional[str] = Query(None, description="YYYY-MM, включительно"),
    month_to:   Optional[str] = Query(None, description="YYYY-MM, включительно"),
    month:      Optional[str] = Query(None, description="YYYY-MM, один месяц"),

    include_top_items: bool = Query(True, description="Включить ТОП-товары"),
    top_items_limit: int    = Query(5, ge=1, le=50, description="Размер ТОП-списка"),
):
    uid = int(user["sub"])

    # --- выбор периода ---
    use_month_mode = any([month, month_from, month_to])
    use_date_mode  = any([date_from, date_to])

    if use_month_mode and use_date_mode:
        raise HTTPException(status_code=422, detail="Нельзя смешивать параметры месяцев и дат. Используйте либо YYYY-MM, либо YYYY-MM-DD.")

    if use_month_mode:
        if month:
            dt_from_norm, dt_to_inc = month_bounds(month)
        else:
            # если указан только один конец — берём один и тот же месяц
            if not month_from and not month_to:
                raise HTTPException(status_code=422, detail="Укажите month или хотя бы month_from/month_to.")
            m_from = month_from or month_to
            m_to   = month_to   or month_from
            start_from, _ = month_bounds(m_from)
            _, end_to     = month_bounds(m_to)
            dt_from_norm, dt_to_inc = start_from, end_to
    else:
        # дефолт — текущий месяц
        if not date_from and not date_to:
            today = datetime.utcnow()
            ym = f"{today.year:04d}-{today.month:02d}"
            dt_from_norm, dt_to_inc = month_bounds(ym)
        else:
            try:
                dt_to   = datetime.strptime(date_to,   "%Y-%m-%d") if date_to   else datetime.utcnow()
                dt_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else (dt_to - timedelta(days=30))
            except ValueError:
                raise HTTPException(status_code=422, detail="Неверный формат даты. Используйте YYYY-MM-DD.")
            dt_from_norm = dt_from.replace(hour=0, minute=0, second=0, microsecond=0)
            dt_to_inc    = dt_to.replace(hour=23, minute=59, second=59, microsecond=999999)

    ts = purchased_at_expr()

    # --- SUMMARY ---
    summary_q = (
        select(
            func.coalesce(func.sum(ReceiptDB.total), 0.0),
            func.count(ReceiptDB.id),
            func.coalesce(func.avg(ReceiptDB.total), 0.0),
            func.count(func.distinct(ReceiptDB.store)),
        )
        .where(
            (ReceiptDB.user_id == uid) &
            (ts >= dt_from_norm) &
            (ts <= dt_to_inc)
        )
    )
    total_spent, purchase_count, avg_ticket, unique_stores = (await db.execute(summary_q)).one()

    # --- BY CATEGORY ---
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
            (ts >= dt_from_norm) &
            (ts <= dt_to_inc)
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

    # --- TOP ITEMS (по ProductDB.name) ---
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
                (ts >= dt_from_norm) &
                (ts <= dt_to_inc)
            )
            .group_by(ProductDB.name)
            .order_by(literal_column("total_spent").desc())
            .limit(top_items_limit)
        )
        for r in (await db.execute(top_q)).all():
            top_items.append(
                TopItem(
                    name=r.name or "—",
                    total_spent=float(r.total_spent or 0),
                    count=int(r.count or 0)
                )
            )

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

# ---------- daily series for charts ----------

@router.get("/statistics/series", summary="Дневные суммы по месяцу (+предыдущий месяц) для графика")
async def get_month_series(
    month: Optional[str] = Query(None, description="YYYY-MM; по умолчанию — текущий месяц"),
    db: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    uid = int(user["sub"])

    # месяц по умолчанию — текущий
    if not month:
        today = datetime.utcnow()
        month = f"{today.year:04d}-{today.month:02d}"

    # текущий и прошлый месяцы (границы включительно)
    cur_from, cur_to = month_bounds(month)
    prev_month = prev_month_str(month)
    prv_from, prv_to = month_bounds(prev_month)

    ts = purchased_at_expr()

    # агрегаты по ДНЯМ текущего месяца
    cur_q = (
        select(
            func.date_trunc('day', ts).label('d'),
            func.coalesce(func.sum(ReceiptDB.total), 0.0).label("sum")
        )
        .where((ReceiptDB.user_id == uid) & (ts >= cur_from) & (ts <= cur_to))
        .group_by(literal_column("d"))
        .order_by(literal_column("d"))
    )
    cur_rows = (await db.execute(cur_q)).all()
    cur_map: Dict[str, float] = {r.d.date().isoformat(): float(r.sum or 0) for r in cur_rows}

    # агрегаты по ДНЯМ прошлого месяца
    prv_q = (
        select(
            func.date_trunc('day', ts).label('d'),
            func.coalesce(func.sum(ReceiptDB.total), 0.0).label("sum")
        )
        .where((ReceiptDB.user_id == uid) & (ts >= prv_from) & (ts <= prv_to))
        .group_by(literal_column("d"))
        .order_by(literal_column("d"))
    )
    prv_rows = (await db.execute(prv_q)).all()
    prv_map: Dict[str, float] = {r.d.date().isoformat(): float(r.sum or 0) for r in prv_rows}

    # полный ряд дней для текущего месяца
    days_in_month = calendar.monthrange(cur_from.year, cur_from.month)[1]
    days: List[str] = [
        datetime(cur_from.year, cur_from.month, d).date().isoformat()
        for d in range(1, days_in_month + 1)
    ]

    current = [cur_map.get(day, 0.0) for day in days]

    # прошлый месяц — выравниваем по номеру дня
    prv_days_in_month = calendar.monthrange(prv_from.year, prv_from.month)[1]
    previous: List[float] = []
    for d in range(1, days_in_month + 1):
        if d <= prv_days_in_month:
            key = datetime(prv_from.year, prv_from.month, d).date().isoformat()
            previous.append(prv_map.get(key, 0.0))
        else:
            previous.append(0.0)

    return {
        "user_id": uid,
        "month": month,
        "days": days,        # ISO-даты текущего месяца (для подписей оси X можно преобразовать на фронте)
        "current": current,  # суммы по дням текущего месяца
        "previous": previous # суммы прошлого месяца, выровненные по номеру дня
    }
