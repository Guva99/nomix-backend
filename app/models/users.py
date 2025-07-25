from typing import Optional

from sqlalchemy import Column, Integer, String
from pydantic import BaseModel
from app.core.database import Base


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    token = Column(String, unique=True)
    auth_date = Column(Integer)


class TelegramUserCreate(BaseModel):
    id: int
    first_name: str
    last_name: str  = None
    username: str  = None
    photo_url: str = None
    token: str
    auth_date: int


# Pydantic модель для ответа API
class UserResponse(BaseModel):
    id: int
    first_name: str
    username: Optional[str]

    class Config:
        from_attributes = True  # Для совместимости с SQLAlchemy