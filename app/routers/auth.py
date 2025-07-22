from fastapi import APIRouter, HTTPException
import httpx
from app.models.users import TelegramUser
import os

router = APIRouter()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

@app.post("/login/")
async def login(data: TelegramUser):
    # Получаем токен с фронта (который присылает Telegram Web App)
    token = data.token
    try:
        # Проверяем токен с помощью API Telegram
        response = await httpx.get(f"https://api.telegram.org/bot{TOKEN}/getMe")
        response_data = response.json()

        if response.status_code == 200 and response_data.get('ok', False):
            # Если токен верный, продолжаем авторизацию
            user_data = response_data.get('result', {})
            # Здесь можно сохранить информацию о пользователе в базе данных
            return {"status": "success", "user": user_data}
        else:
            raise HTTPException(status_code=400, detail="Invalid token")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"Error connecting to Telegram API: {e}")
