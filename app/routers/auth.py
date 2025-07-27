import hmac
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
import urllib.parse


from app.models.users import TelegramUserCreate, UserResponse
from app.core.database import get_db_session

router = APIRouter()


def generate_token() -> str:
    return secrets.token_hex(16)


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
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.fetchone()

        token = generate_token() if not existing_user else existing_user.token

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
                {
                    "id": user_data.id,
                    "first_name": user_data.first_name,
                    "last_name": user_data.last_name,
                    "username": user_data.username,
                    "photo_url": photo_url_jpg,
                    "token": token
                }
            )
        else:
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
            "id": user_data.id,
            "photoUrl": photo_url_jpg,
            "token": token
        }

    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")


@router.post("/validate")
async def validate_token(
        payload: dict,
        db: AsyncSession = Depends(get_db_session)
):
    user_id = payload.get("id")
    token = payload.get("token")

    if not user_id or not token:
        raise HTTPException(status_code=400, detail="Missing id or token")

    result = await db.execute(
        text("SELECT token FROM users WHERE id = :id"),
        {"id": user_id}
    )
    stored = result.scalar_one_or_none()

    if stored and stored == token:
        return {"message": "valid"}

    raise HTTPException(status_code=401, detail="invalid token")