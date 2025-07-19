import logging
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
    logger.info("FastAPI startup → init bot + webhook")
    await bot.initialize()
    await bot.setup_webhook()
    # Запускаем внутренний цикл python-telegram-bot
    await bot.application.start()

# ——— Обработчик Telegram webhook ———
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        payload = await request.json()
        upd = Update.de_json(payload, bot.application.bot)
        await bot.process_update(upd)
        return {"ok": True}
    except Exception as exc:
        logger.exception("webhook error")
        raise HTTPException(status_code=500, detail=str(exc))

# ——— SPA fallback для Flutter (client-side routing) ———
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request: Request):
    # Не обрабатываем API, статические файлы и webhook
    if request.url.path.startswith(("/static", "/api", "/webhook")):
        raise HTTPException(status_code=404)

    index = FLUTTER_WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=500, detail="Flutter build missing")
    return FileResponse(index)

# ——— CORS ———
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
