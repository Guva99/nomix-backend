import logging
from pathlib import Path
import urllib.parse

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.routers import auth
from app.routers.callback import router as callback_router
from app.services.bot import bot, on_startup
from telegram import Update

# === Настройка логов ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# === Инициализация FastAPI ===
app = FastAPI()
FLUTTER_WEB_DIR = Path("/app/frontend/build/web")
templates = Jinja2Templates(directory="/app/frontend/templates")

# === Монтируем Flutter-статик ===
app.mount("/static", StaticFiles(directory=str(FLUTTER_WEB_DIR)), name="static")
app.mount("/", StaticFiles(directory=str(FLUTTER_WEB_DIR), html=True), name="flutter")

# === Подключаем роутеры ===
app.include_router(auth.router)
app.include_router(callback_router)

# === Хук на запуске ===
@app.on_event("startup")
async def startup():
    logger.info("Starting bot and FastAPI app...")
    await on_startup()

# === Webhook для Telegram ===
@app.post("/webhook")
async def webhook(request: Request):
    try:
        update_data = await request.json()
        logger.info(f"Received update: {update_data}")

        update = Update.de_json(update_data, bot.bot)
        await bot.process_update(update)
        return {"ok": True}

    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

# === Fallback-маршрут Flutter SPA ===
@app.get("/{full_path:path}")
async def flutter_route_fallback(full_path: str, request: Request):
    logger.info(f"Request received - Path: {full_path}, Query: {request.query_params}")

    tg_params = {
        'tgWebAppData': request.query_params.get('tgWebAppData'),
        'tgWebAppVersion': request.query_params.get('tgWebAppVersion'),
        'tgWebAppPlatform': request.query_params.get('tgWebAppPlatform'),
        'tgWebAppThemeParams': request.query_params.get('tgWebAppThemeParams')
    }

    if any(tg_params.values()):
        logger.info(f"Telegram Web App detected with params: {tg_params}")

    index_path = FLUTTER_WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index file not found")

    return FileResponse(index_path)

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
