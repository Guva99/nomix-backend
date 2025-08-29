from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db_session
from app.models.db.product import ProductDB

router = APIRouter()

@router.get("/products/{product_id}")
async def get_product(product_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(ProductDB).where(ProductDB.id == product_id))
    product = result.scalar()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "barcode": product.barcode,
        "category": product.category,
        "category_id": product.category_id,
        "subcategory": product.subcategory,
        "subcategory_id": product.subcategory_id
    }