from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String
from app.core.database import Base


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)

def to_camel(string: str) -> str:
    parts = string.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])

class TelegramUserCreate(BaseModel):
    id: int
    first_name: str = Field(..., alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    username: Optional[str]
    photo_url: Optional[str] = Field(None, alias="photoUrl")

    class Config:
        alias_generator = to_camel
        populate_by_name = True
        allow_population_by_field_name = True


class UserResponse(BaseModel):
    id: int
    first_name: str = Field(..., alias="firstName")
    username: Optional[str]
    photo_url: Optional[str] = Field(None, alias="photoUrl")
    token: str

    class Config:
        alias_generator = to_camel
        populate_by_name = True
        allow_population_by_field_name = True
        from_attributes = True
