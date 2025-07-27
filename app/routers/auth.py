from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

import urllib.parse
from app.utils.auth import generate_token

from app.models.users import TelegramUserCreate, UserResponse
from app.core.database import get_db_session

router = APIRouter()



@router.post("/login")
async def login(
    user_data: TelegramUserCreate,
    db: AsyncSession = Depends(get_db_session)
):
    try:
        def convert_svg_to_jpg(url: str) -> str:
            if not url:
                return ""
            decoded = urllib.parse.unquote(url)
            return decoded.replace(".svg", ".jpg") if decoded.endswith(".svg") else decoded

        photo_url_jpg = convert_svg_to_jpg(user_data.photo_url)

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
                    "photo_url": photo_url_jpg,
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
                    "photo_url": photo_url_jpg,
                    "token": token
                }
            )

        await db.commit()

        return {
            "message": "success",
            "code": 200,
            "id": user_data.id,
            "photoUrl": photo_url_jpg,
            "token": token
        }


    except Exception as e:
        await db.rollback()
        import logging
        logging.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Database error")

