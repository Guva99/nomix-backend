import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.routers import auth
from app.routers.callback import router as callback_router
from app.services.bot import bot, on_startup
from pathlib import Path
from starlette.responses import HTMLResponse
import urllib.parse

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI()
FLUTTER_WEB_DIR = Path("/app/frontend/build/web")

# Устанавливаем шаблоны для FastAPI (если понадобятся для других целей)
templates = Jinja2Templates(directory="/app/frontend/templates")

@app.get("/{full_path:path}")
async def flutter_route_fallback(full_path: str, request: Request):
    # Логируем полученные данные
    logger.info(f"Request received - Path: {full_path}, Query: {request.query_params}")

    tg_params = {
        'tgWebAppData': request.query_params.get('tgWebAppData'),
        'tgWebAppVersion': request.query_params.get('tgWebAppVersion'),
        'tgWebAppPlatform': request.query_params.get('tgWebAppPlatform'),
        'tgWebAppThemeParams': request.query_params.get('tgWebAppThemeParams')
    }

    if any(tg_params.values()):
        logger.info(f"Telegram Web App detected with params: {tg_params}")
        # Распакуйте или используйте tgWebAppData по необходимости

    # Возвращаем основной HTML
    index_path = FLUTTER_WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index file not found")

    return FileResponse(index_path)

@app.on_event("startup")
async def startup():
    logger.info("Starting bot and FastAPI app...")
    await on_startup()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update_data = await request.json()

        # Базовая проверка формата обновления Telegram
        if not isinstance(update_data, dict) or 'update_id' not in update_data:
            logger.warning(f"Invalid update format: {update_data}")
            return {"ok": False, "error": "Invalid update format"}

        await bot.process_update(update_data)
        return {"ok": True}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
