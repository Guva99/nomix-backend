from pydantic import BaseModel
from typing import List, Dict, Optional

class StorePriceInfo(BaseModel):
    store: str
    price: float
    date: str
    price_per_unit: float

class ProductStatsResponse(BaseModel):
    product_id: int
    product_name: str
    period: str
    total_purchases: int
    stores_info: List[StorePriceInfo]
    average_price: float
    min_price: float
    total_spent: float
    best_store: Optional[str] = None
    savings: Optional[float] = None