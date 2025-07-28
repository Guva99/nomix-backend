from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from urllib.parse import urlparse
import logging
import os

from app.utils.auth import generate_token
from app.models.users import TelegramUserCreate
from app.core.database import get_db_session
from app.services.bot import get_avatar_url  # Получение аватарки через Telegram Bot API

router = APIRouter()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@router.post("/login")
async def login(
    user_data: TelegramUserCreate,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        # Получаем ссылку на фото через Telegram Bot API
        telegram_file_url = await get_avatar_url(user_data.id)

        # Преобразуем URL Telegram API в проксируемый путь
        avatar_proxy_url = None
        if telegram_file_url:
            parsed = urlparse(telegram_file_url)
            if parsed.path:
                # Удаляем префикс `/file/bot<TOKEN>/`
                proxy_path = parsed.path.replace(f"/file/bot{TELEGRAM_BOT_TOKEN}/", "")
                avatar_proxy_url = f"/api/telegram/avatar/{proxy_path}"

        # Ищем пользователя в БД
        result = await db.execute(
            text("SELECT token FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.fetchone()

        if existing_user:
            # Обновляем только основные поля, токен не трогаем
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
                    "photo_url": avatar_proxy_url,
                }
            )
            token = existing_user.token
        else:
            # Новый пользователь — создаём токен и запись
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
                    "photo_url": avatar_proxy_url,
                    "token": token
                }
            )

        await db.commit()

        return {
            "message": "success",
            "code": 200,
            "id": user_data.id,
            "photoUrl": avatar_proxy_url,
            "token": token
        }

    except Exception as e:
        await db.rollback()
        logging.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
