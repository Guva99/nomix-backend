from typing import Optional, List

from pydantic import BaseModel, Field


class CategoryStat(BaseModel):
    category_id: int
    category: Optional[str] = None
    total_spent: float
    purchase_count: int
    avg_item_price: float

class Summary(BaseModel):
    total_spent: float
    purchase_count: int
    avg_ticket: float
    unique_stores: int

class TopItem(BaseModel):
    name: str
    total_spent: float
    count: int

class StatisticsResponse(BaseModel):
    user_id: int
    date_from: str
    date_to: str
    summary: Summary
    by_category: List[CategoryStat]
    top_items: List[TopItem] = Field(default_factory=list)
