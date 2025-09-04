from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Depends, Header  # ⬅️ Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db_session
from app.services.jwt import verify_access_token  # ⬅️ JWT

router = APIRouter()

@router.get("/user")
async def get_user_data(
    id: int = Query(None),
    token: str = Query(None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session)
):
    # A) Bearer приоритетно
    if authorization and authorization.lower().startswith("bearer "):
        payload = verify_access_token(authorization.split(" ", 1)[1].strip())
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        id = int(payload["sub"])

        result = await db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": id})
        user = result.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

    # B) Легаси-путь (пока оставляем)
    else:
        if id is None or token is None:
            raise HTTPException(status_code=400, detail="Передай id и token или Bearer")
        result = await db.execute(
            text("SELECT * FROM users WHERE id = :id AND token = :token"),
            {"id": id, "token": token}
        )
        user = result.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token or user not found")

    return {
        "id": user.id,
        "firstName": user.first_name,
        "username": user.username,
        "photoUrl": user.photo_url
    }
