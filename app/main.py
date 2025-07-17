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

# Монтируем директорию для статики (собранные файлы Flutter)
app.mount("/static", StaticFiles(directory=str(FLUTTER_WEB_DIR)), name="static")
app.mount("/", StaticFiles(directory=str(FLUTTER_WEB_DIR), html=True), name="flutter")

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(callback_router)

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

@app.get("/{full_path:path}")
async def flutter_route_fallback(full_path: str, request: Request):
    logger.info(f"Request full path: {full_path}")
    tg_web_app_data = request.query_params.get('tgWebAppData')
    if tg_web_app_data:
        logger.info(f"Received tgWebAppData: {tg_web_app_data}")
    return HTMLResponse((FLUTTER_WEB_DIR / "index.html").read_text(), media_type="text/html")


# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
