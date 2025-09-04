from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from app.utils.auth import generate_token
from app.models.users import TelegramUserCreate
from app.core.database import get_db_session
from app.services.bot import bot
from app.services.jwt import create_access_token

router = APIRouter()

@router.post("/login")
async def login(
    user_data: TelegramUserCreate,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        # Аватарка пользователя
        avatar_base64 = await bot.get_avatar_base64(user_data.id)

        # Проверяем, есть ли пользователь
        result = await db.execute(
            text("SELECT token FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.fetchone()

        if existing_user:
            await db.execute(
                text("""
                    UPDATE users
                    SET first_name = :first_name,
                        last_name  = :last_name,
                        username   = :username,
                        photo_url  = :photo_url
                    WHERE id = :id
                """),
                {
                    "id": user_data.id,
                    "first_name": user_data.first_name,
                    "last_name": user_data.last_name,
                    "username": user_data.username,
                    "photo_url": avatar_base64,
                }
            )
            token = existing_user.token
        else:
            token = generate_token()
            await db.execute(
                text("""
                    INSERT INTO users
                        (id, first_name, last_name, username, photo_url, token)
                    VALUES (:id, :first_name, :last_name, :username, :photo_url, :token)
                """),
                {
                    "id": user_data.id,
                    "first_name": user_data.first_name,
                    "last_name": user_data.last_name,
                    "username": user_data.username,
                    "photo_url": avatar_base64,
                    "token": token
                }
            )

        await db.commit()

        # ⬇️ ГЛАВНОЕ: начинаем выдавать Bearer (JWT)
        access_token = create_access_token({"sub": str(user_data.id)})

        return {
            "message": "success",
            "code": 200,
            "id": user_data.id,
            "photoUrl": avatar_base64,
            "token": token,                 # legacy (пока не ломаем)
            "access_token": access_token,   # НОВОЕ — используй как Bearer
            "token_type": "Bearer"
        }

    except Exception as e:
        await db.rollback()
        logging.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
