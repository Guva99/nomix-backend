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
from app.services.bot import dp, bot
from app.routers.auth import router as login
from app.routers.data import router as data
from app.routers.gpt import router as gpt
from app.routers.Checks import router as checks
from app.routers.products import router as products
from aiogram.types import Update



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
app.include_router(login, prefix="/api/telegram", tags=["Telegram"])
app.include_router(data, prefix="/api/data", tags=["Database"])
app.include_router(gpt, prefix="/api/bot", tags=["GPT"])
app.include_router(checks, prefix="/api/receipts", tags=["Receipts"])
app.include_router(products, prefix="/api", tags=["Products"])



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
async def telegram_webhook(req: Request):
    data = await req.json()
    await bot.process_update(data)
    return {"ok": True}

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
