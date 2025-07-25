from fastapi import APIRouter, Depends, HTTPException
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.users import TelegramUserCreate, UserResponse, UserDB
from app.core.database import get_db_session
import os
from sqlalchemy import text

router = APIRouter()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@router.post("/login/", response_model=UserResponse)
async def login(
        user_data: TelegramUserCreate,
        db: AsyncSession = Depends(get_db_session)
):
    # 1. Проверяем токен через Telegram API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.telegram.org/bot{TOKEN}/getMe",
                timeout=10.0
            )
            response.raise_for_status()

            if not response.json().get("ok"):
                raise HTTPException(status_code=401, detail="Invalid Telegram token")

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail="Telegram API unavailable")

    # 2. Сохраняем/обновляем пользователя в БД
    try:
        # Проверяем существование пользователя
        result = await db.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # Обновляем данные
            await db.execute(
                text("""
                     UPDATE users
                     SET first_name = :first_name,
                         last_name  = :last_name,
                         username   = :username,
                         photo_url  = :photo_url,
                         token      = :token,
                         auth_date  = :auth_date
                     WHERE id = :id
                     """),
                user_data.model_dump()
            )
        else:
            # Создаем нового пользователя
            await db.execute(
                text("""
                     INSERT INTO users
                         (id, first_name, last_name, username, photo_url, token, auth_date)
                     VALUES (:id, :first_name, :last_name, :username, :photo_url, :token, :auth_date)
                     """),
                user_data.model_dump()
            )

        await db.commit()

        # Возвращаем данные пользователя
        return UserResponse(
            id=user_data.id,
            first_name=user_data.first_name,
            username=user_data.username
        )

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")