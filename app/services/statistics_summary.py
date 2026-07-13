from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.product import ProductDB
from app.models.db.receipt import ReceiptDB, ReceiptItemDB
from app.routers.statistics import month_bounds, purchased_at_expr


async def fetch_month_statistics(
    db: AsyncSession,
    user_id: int,
    month: str | None = None,
    items_limit: int = 5,
) -> dict[str, Any]:
    if not month:
        today = datetime.utcnow()
        month = f"{today.year:04d}-{today.month:02d}"

    dt_from, dt_to = month_bounds(month)
    ts = purchased_at_expr()
    uid = int(user_id)

    summary_q = (
        select(
            func.coalesce(func.sum(ReceiptDB.total), 0.0),
            func.count(ReceiptDB.id),
            func.coalesce(func.avg(ReceiptDB.total), 0.0),
            func.count(func.distinct(ReceiptDB.store)),
        )
        .where(
            (ReceiptDB.user_id == uid)
            & (ts >= dt_from)
            & (ts <= dt_to)
        )
    )
    total_spent, purchase_count, avg_ticket, unique_stores = (await db.execute(summary_q)).one()

    cats_q = (
        select(
            ProductDB.category.label("cname"),
            func.coalesce(func.sum(ReceiptItemDB.price), 0.0).label("total_spent"),
        )
        .join(ReceiptDB, ReceiptDB.id == ReceiptItemDB.receipt_id)
        .join(ProductDB, ProductDB.id == ReceiptItemDB.product_id, isouter=True)
        .where(
            (ReceiptDB.user_id == uid)
            & (ts >= dt_from)
            & (ts <= dt_to)
        )
        .group_by(ProductDB.category)
        .order_by(literal_column("total_spent").desc())
        .limit(8)
    )
    cat_rows = (await db.execute(cats_q)).all()

    return {
        "month": month,
        "summary": {
            "total_spent": float(total_spent or 0),
            "purchase_count": int(purchase_count or 0),
            "avg_ticket": float(avg_ticket or 0),
            "unique_stores": int(unique_stores or 0),
        },
        "categories": [
            {
                "category": r.cname or "Прочее",
                "total_spent": float(r.total_spent or 0),
            }
            for r in cat_rows
        ],
    }


_RU_MONTHS = (
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def format_month_stats_message(stats: dict[str, Any]) -> str:
    month = stats["month"]
    y, m = map(int, month.split("-"))
    month_name = f"{_RU_MONTHS[m].capitalize()} {y}"

    s = stats["summary"]
    lines = [
        f"📈 <b>Статистика за {month_name}</b>",
        "",
        f"💰 Потрачено: <b>{s['total_spent']:,.2f} ₽</b>",
        f"🧾 Чеков: <b>{s['purchase_count']}</b>",
        f"📊 Средний чек: <b>{s['avg_ticket']:,.2f} ₽</b>",
        f"🏪 Магазинов: <b>{s['unique_stores']}</b>",
    ]

    cats = stats.get("categories") or []
    if cats:
        lines.append("")
        lines.append("<b>По категориям:</b>")
        for cat in cats:
            lines.append(f"• {cat['category']}: {cat['total_spent']:,.2f} ₽")

    if s["purchase_count"] == 0:
        lines.append("")
        lines.append("Пока нет сохранённых чеков за этот месяц. Отправь фото чека 🧾")

    return "\n".join(lines)
