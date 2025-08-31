from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List, Optional

from app.core.database import get_db_session
from app.models.ProductStats import ProductStatsResponse, StorePriceInfo
from app.models.db.product import ProductDB
from app.models.db.receipt import ReceiptDB, ReceiptItemDB

router = APIRouter()


@router.get("/products/{product_id}")
async def get_product(product_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(ProductDB).where(ProductDB.id == product_id))
    product = result.scalar()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Получаем статистику покупок
    purchase_result = await db.execute(
        select(func.count(ReceiptItemDB.id))
        .where(ReceiptItemDB.product_id == product_id)
    )
    purchase_count = purchase_result.scalar() or 0

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "barcode": product.barcode,
        "category": product.category,
        "category_id": product.category_id,
        "subcategory": product.subcategory,
        "subcategory_id": product.subcategory_id,
        "purchase_count": purchase_count
    }

@router.get("/products/{product_id}/stats", response_model=ProductStatsResponse)
async def get_product_stats(
        product_id: int,
        period: str = Query("all", description="Период: day, week, month, year, all"),
        db: AsyncSession = Depends(get_db_session)
):
    # Проверяем существование продукта
    result = await db.execute(select(ProductDB).where(ProductDB.id == product_id))
    product = result.scalar()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Базовый запрос для получения покупок продукта
    query = (
        select(
            ReceiptDB.store,
            ReceiptItemDB.price,
            ReceiptDB.date,
            ReceiptDB.id
        )
        .join(ReceiptItemDB, ReceiptItemDB.receipt_id == ReceiptDB.id)
        .where(ReceiptItemDB.product_id == product_id)
    )

    # Фильтрация по периоду
    if period != "all":
        today = datetime.now().date()
        if period == "day":
            start_date = today
        elif period == "week":
            start_date = today - timedelta(days=7)
        elif period == "month":
            start_date = today - timedelta(days=30)
        elif period == "year":
            start_date = today - timedelta(days=365)
        else:
            raise HTTPException(status_code=400, detail="Invalid period")

        query = query.where(ReceiptDB.date >= start_date.isoformat())

    # Выполняем запрос
    result = await db.execute(query)
    purchases = result.all()

    if not purchases:
        raise HTTPException(status_code=404, detail="No purchases found for this product")

    # Анализируем данные
    stores_info = []
    total_spent = 0
    prices = []

    for store, price, purchase_date, receipt_id in purchases:
        # Для простоты считаем цену за единицу (можно доработать для учета количества)
        price_per_unit = price
        stores_info.append(StorePriceInfo(
            store=store,
            price=price,
            date=purchase_date,
            price_per_unit=price_per_unit
        ))
        total_spent += price
        prices.append(price_per_unit)

    # Находим лучший магазин и экономию
    min_price = min(prices)
    max_price = max(prices)
    average_price = total_spent / len(purchases)

    # Находим магазин с минимальной ценой
    best_store_info = next((s for s in stores_info if s.price_per_unit == min_price), None)
    best_store = best_store_info.store if best_store_info else None

    # Рассчитываем потенциальную экономию (если бы все покупки были по минимальной цене)
    savings = total_spent - (min_price * len(purchases))

    return ProductStatsResponse(
        product_id=product.id,
        product_name=product.name,
        period=period,
        total_purchases=len(purchases),
        stores_info=stores_info,
        average_price=round(average_price, 2),
        min_price=round(min_price, 2),
        total_spent=round(total_spent, 2),
        best_store=best_store,
        savings=round(savings, 2) if savings > 0 else 0
    )


@router.get("/products/search/{product_name}")
async def search_products(
        product_name: str,
        db: AsyncSession = Depends(get_db_session)
):
    result = await db.execute(
        select(ProductDB)
        .where(ProductDB.name.ilike(f"%{product_name}%"))
        .limit(10)
    )
    products = result.scalars().all()

    return [{
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category
    } for p in products]