from sqlalchemy import Column, Integer, String
from pydantic import BaseModel
from app.core.database import Base

class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: str
    username: str
    photo_url: str