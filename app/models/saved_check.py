from typing import List, Optional, Union
from pydantic import BaseModel, field_validator

NumberLike = Union[int, float, str]

# models/saved_check.py
class ReceiptItem(BaseModel):
    name: str
    price: float
    category: str
    category_id: int = 0
    subcategory: Optional[str] = ""
    subcategory_id: int = 0
    product_id: Optional[int] = None  # <-- новое поле

    @field_validator("price", mode="before")
    @classmethod
    def _cast_price(cls, v: NumberLike):
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        return float(v)

    @field_validator("category_id", "subcategory_id", mode="before")
    @classmethod
    def _cast_ints(cls, v):
        if v in (None, "", "null"):
            return 0
        if isinstance(v, str):
            v = v.strip()
        return int(v)

class SaveReceiptPayload(BaseModel):
    user_id: int
    store: str
    date: str                   # "YYYY-MM-DD"
    time: Optional[str] = ""    # пусть будет пустой по умолчанию
    total: float
    currency: str
    image_url: Optional[str] = None
    items: List[ReceiptItem]

    @field_validator("total", mode="before")
    @classmethod
    def _cast_total(cls, v: NumberLike):
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        return float(v)

    class Config:
        extra = "ignore"  # игнорим лишние поля, если вдруг пришли
