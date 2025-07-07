from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import hashlib
import hmac
from core.settings import settings

router = APIRouter()

@router.post("/callback")
async def callback(request: Request):
    data = await request.json()

    auth_date = data.get("auth_date")
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    username = data.get("username")
    user_id = data.get("id")
    photo_url = data.get("photo_url")
    hash_received = data.get("hash")

    data_check_string = f"auth_date={auth_date}\nfirst_name={first_name}\nid={user_id}\nusername={username}"

    secret_key = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).hexdigest()

    # Проверяем хэш
    hash_calculated = hmac.new(bytes(secret_key, 'utf-8'), msg=bytes(data_check_string, 'utf-8'), digestmod=hashlib.sha256).hexdigest()

    # Если хэш совпадает, возвращаем данные пользователя
    if hash_received == hash_calculated:
        # Тут можно сохранить данные пользователя в базу данных или выполнить другие действия
        return JSONResponse(content={
            "status": "success",
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "photo_url": photo_url
        })
    else:
        return JSONResponse(content={"status": "error", "message": "Invalid hash"}, status_code=400)
