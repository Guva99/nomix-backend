import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update

from app.services.bot import bot  # <- импорт синглтона TelegramBot

# ——— Настройка логирования ———
logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ——— Инициализация FastAPI ———
app = FastAPI()

# Каталог, куда собирается Flutter Web
FLUTTER_WEB_DIR = Path("/frontend_build")  # соответствует FLUTTER_WEB_DIR в Dockerfile

# Монтируем статику из папки build/web
app.mount("/static", StaticFiles(directory=str(FLUTTER_WEB_DIR)), name="static")

# ——— Событие старта: инициализируем бота и настраиваем webhook ———
@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting FastAPI application")

    # Инициализация бота
    try:
        await bot.initialize()
        webhook_info = await bot.application.bot.get_webhook_info()
        logger.info(f"Current webhook info: {webhook_info}")

        await bot.setup_webhook()
        await bot.application.start()

        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.critical(f"Bot initialization failed: {e}")
        raise

# ——— Обработчик Telegram webhook ———
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        # Добавляем логирование входящего вебхука
        body = await request.body()
        logger.debug(f"Incoming webhook: {body.decode()[:200]}...")

        payload = await request.json()
        upd = Update.de_json(payload, bot.application.bot)

        # Проверка версии для Mini App (исправленная версия)
        if hasattr(upd, 'web_app_data') and upd.web_app_data is not None:
            logger.info(f"WebApp version check for user {upd.effective_user.id if upd.effective_user else 'unknown'}")

        await bot.process_update(upd)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=500, detail=str(exc))

# ——— SPA fallback для Flutter (client-side routing) ———
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request: Request):
    # Исключаем API и статические файлы
    if request.url.path.startswith(("/static", "/api", "/webhook")):
        raise HTTPException(status_code=404)

    # Добавляем параметр версии для index.html
    index = FLUTTER_WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=500, detail="Flutter build missing")

    response = FileResponse(index)
    # Жесткие заголовки против кэширования
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-App-Version"] = "1.0.3"  # Обновляйте при каждом деплое
    return response

@app.get("/api/force_refresh")
async def force_refresh(request: Request):
    """
    Эндпоинт для принудительного обновления клиента
    Используется в сочетании с Telegram.WebApp.openLink()
    """
    return {
        "status": "refresh_required",
        "new_url": f"https://{request.url.hostname}/?v={datetime.now().timestamp()}",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/version")
async def get_app_version():
    return {
        "version": "1.0.3",
        "build_date": "2025-07-21",
        "telegram_compatible": True
    }

# ——— CORS ———
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
