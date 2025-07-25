import hmac
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os

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
        result = await db.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_data.id}
        )
        existing_user = result.fetchone()

        if existing_user:
            token = existing_user.token or generate_token()
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
                {**user_data.model_dump(), "token": token}
            )
        else:
            token = generate_token()
            await db.execute(
                text("""
                    INSERT INTO users
                        (id, first_name, last_name, username, photo_url, token)
                    VALUES (:id, :first_name, :last_name, :username, :photo_url, :token)
                """),
                {**user_data.model_dump(), "token": token}
            )

        await db.commit()
        return {"message": "success", "token": token}

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