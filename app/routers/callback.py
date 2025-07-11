from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import hashlib
import hmac
from core.settings import settings

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")

@router.get("/callback", response_class=HTMLResponse)
async def callback(request: Request):
    params = request.query_params

    # Извлекаем данные
    auth_date = params.get("auth_date")
    first_name = params.get("first_name")
    last_name = params.get("last_name")
    username = params.get("username")
    user_id = params.get("id")
    photo_url = params.get("photo_url")
    hash_received = params.get("hash")

    # Проверка подписи
    data_check_string = '\n'.join([
        f"auth_date={auth_date}",
        f"first_name={first_name}",
        f"id={user_id}",
        f"username={username}"
    ])
    secret_key = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    hmac_hash = hmac.new(secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()

    if hmac_hash != hash_received:
        return HTMLResponse(content="❌ Ошибка проверки подписи!", status_code=400)

    user_data = {
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "photo_url": photo_url
    }

    # Можно здесь сохранить в БД!

    return templates.TemplateResponse("callback.html", {
        "request": request,
        "user": user_data
    })