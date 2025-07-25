import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update

from app.core.database import engine, Base
from app.services.bot import bot
from app.routers.auth import router as login
from app.routers.callback import router as callback
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
    version="1.0.4",
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
app.include_router(callback, prefix="/api/telegram", tags=["telegram"])

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


@app.post("/api/telegram/webhook", tags=["telegram"])
async def telegram_webhook(request: Request):
    try:
        body = await request.body()
        logger.debug(f"Incoming webhook: {body.decode()[:200]}...")

        payload = await request.json()
        upd = Update.de_json(payload, bot.application.bot)

        if hasattr(upd, 'web_app_data') and upd.web_app_data is not None:
            user_id = upd.effective_user.id if upd.effective_user else 'unknown'
            logger.info(f"WebApp event from user {user_id}")

        await bot.process_update(upd)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=500, detail=str(exc))




app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)
