import asyncio
import logging
import os
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from telegram import Update
import json
from app.core.database import engine, Base
from app.services.bot import bot
from app.routers.auth import router as login
from app.routers.data import router as data
from app.routers.gpt import router as gpt
from app.routers.Checks import router as checks
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
app.include_router(checks, prefix="/api/checks", tags=["Checks"])



@app.on_event("startup")
async def on_startup():
    max_retries = int(os.getenv("DATABASE_MAX_RETRIES", "10"))
    retry_delay = int(os.getenv("DATABASE_RETRY_DELAY", "5"))

    # Подключение к БД с повторами
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                logger.info("✅ Database connection established successfully")
                break
        except Exception as e:
            if attempt == max_retries - 1:
                logger.critical(f"❌ Failed to connect to DB after {max_retries} attempts")
                raise
            logger.warning(f"⚠️ DB connection failed (attempt {attempt + 1}), retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)

    # Инициализация бота
    try:
        await bot.initialize()
        await bot.setup_webhook()
        logger.info("🤖 Bot initialized successfully")
    except Exception as e:
        logger.critical(f"❌ Bot initialization failed: {e}")
        raise


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        # Получаем сырые данные для логирования
        raw_body = await request.body()
        logger.info(f"Raw webhook data: {raw_body.decode()}")

        try:
            update_data = await request.json()
        except json.JSONDecodeError as je:
            logger.error(f"JSON decode error: {je}")
            return JSONResponse(
                content={"ok": False, "error": "Invalid JSON"},
                status_code=400
            )

        # Валидация обязательных полей
        if not update_data.get('update_id'):
            logger.error("Missing update_id in payload")
            return JSONResponse(
                content={"ok": False, "error": "Missing update_id"},
                status_code=400
            )

        # Создаем объект Update
        try:
            update = Update.de_json(update_data, bot.application.bot)
            if not update:
                raise ValueError("Empty update object")
        except Exception as e:
            logger.error(f"Update parsing error: {e}")
            return JSONResponse(
                content={"ok": False, "error": "Invalid update format"},
                status_code=400
            )

        # Обработка update
        try:
            await bot.process_update(update)
            return {"ok": True}
        except Exception as e:
            logger.error(f"Update processing error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        logger.exception("Unexpected error in webhook")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health_check():
    """Эндпоинт для проверки работоспособности"""
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        return {
            "status": "ok",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)
