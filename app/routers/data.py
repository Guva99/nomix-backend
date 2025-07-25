from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db_session

router = APIRouter()

@router.get("/user/data")
async def get_user_data(
    id: int = Query(...),
    token: str = Query(...),
    db: AsyncSession = Depends(get_db_session)
):
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
