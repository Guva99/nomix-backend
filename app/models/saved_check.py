from typing import List, Optional
from pydantic import BaseModel

class ReceiptItem(BaseModel):
    name: str
    price: float
    category: str
    category_id: int
    subcategory: Optional[str] = ""
    subcategory_id: int

class SaveReceiptPayload(BaseModel):
    user_id: int
    store: str
    date: str
    time: Optional[str] = ""
    total: float
    currency: str
    image_url: Optional[str] = None
    items: List[ReceiptItem]

    class Config:
        extra = "ignore"