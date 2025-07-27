from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.utils.auth import generate_token
from app.models.users import TelegramUserCreate, UserResponse
from app.core.database import get_db_session
from app.services.bot import get_avatar_url  # Импорт get_avatar_url

router = APIRouter()

@router.post("/login")
async def login(
    user_data: TelegramUserCreate,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        # ⚠️ Получаем ссылку на фото через Telegram Bot API
        photo_url = await get_avatar_url(user_data.id)

        result = await db.execute(
            text("SELECT token FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.fetchone()

        if existing_user:
            # Обновляем только основные данные, токен не трогаем
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
                    "photo_url": photo_url,
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
                    "photo_url": photo_url,
                    "token": token
                }
            )

        await db.commit()

        return {
            "message": "success",
            "code": 200,
            "id": user_data.id,
            "photoUrl": photo_url,
            "token": token
        }

    except Exception as e:
        await db.rollback()
        import logging
        logging.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
