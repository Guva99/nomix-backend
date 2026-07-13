from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict
import jwt

from app.core.settings import settings

JWT_SECRET = settings.JWT_SECRET
JWT_ALG = "HS256"
JWT_EXP_MIN = settings.JWT_EXP_MIN

def create_access_token(payload: Dict[str, Any], exp_minutes: int = JWT_EXP_MIN) -> str:
    now = datetime.utcnow()
    to_encode = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
    }
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def verify_access_token(token: str) -> Dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        return None
