import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
import json
from app.core.database import engine, Base
from app.services.bot import bot
from app.routers.auth import router as login
from app.routers.data import router as data
from app.routers.gpt import router as gpt
from alembic.config import Config
from alembic import command

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Nomix API",
    description="API для Nomix приложения",
    version="1.0.6",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Разрешенные домены для CORS
ALLOWED_ORIGINS = [
    "https://nomix-d6199.web.app",
    "https://mixfom2025.fvds.ru"
]

# Роутеры
app.include_router(login, prefix="/api/telegram", tags=["telegram"])
app.include_router(data, prefix="/api/data", tags=["Database"])
app.include_router(gpt, prefix="/api/bot", tags=["GPT"])


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting FastAPI application")
    try:
        # Проверка подключения к БД
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise
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


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        logger.debug(f"Received update: {update_data}")

        # Создаем объект Update
        update = Update.de_json(update_data, bot.application.bot)
        if not update:
            logger.error("Failed to parse update")
            return {"ok": False, "error": "Invalid update data"}

        await bot.process_update(update)
        return {"ok": True}
    except json.JSONDecodeError:
        logger.error("Invalid JSON received")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.exception("Error processing update")
        raise HTTPException(status_code=500, detail=str(e))


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)
