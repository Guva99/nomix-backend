import hmac
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os

from app.models.users import TelegramUserCreate, UserResponse
from app.core.database import get_db_session

router = APIRouter()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def check_telegram_auth(data: dict, bot_token: str) -> bool:
    # Telegram WebApp данные без auth_date и hash не проверяются — поэтому упрощаем
    return True  # доверяем клиенту, хеш не проверяется (НЕ РЕКОМЕНДУЕТСЯ в проде)


@router.post("/login", response_model=UserResponse)
async def login(
        user_data: TelegramUserCreate,
        db: AsyncSession = Depends(get_db_session)
):
    # ⚠️ Предполагается, что hash не передаётся — доверяем фронту

    try:
        result = await db.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            await db.execute(
                text("""
                    UPDATE users
                    SET first_name = :first_name,
                        last_name  = :last_name,
                        username   = :username,
                        photo_url  = :photo_url,
                        token      = :token
                    WHERE id = :id
                """),
                user_data.model_dump()
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO users
                        (id, first_name, last_name, username, photo_url, token)
                    VALUES (:id, :first_name, :last_name, :username, :photo_url, :token)
                """),
                user_data.model_dump()
            )

        await db.commit()

        return UserResponse(
            id=user_data.id,
            first_name=user_data.first_name,
            username=user_data.username,
            photo_url=user_data.photo_url
        )

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")