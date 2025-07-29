import asyncio
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
async def on_startup():
    max_retries = 5
    retry_delay = 3

    # Подключение к БД с повторами
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if attempt == max_retries - 1:
                logger.critical(f"Failed to connect to DB after {max_retries} attempts")
                raise
            logger.warning(f"DB connection failed (attempt {attempt + 1}), retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)

    # Инициализация бота
    await bot.initialize()
    await bot.setup_webhook()


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
