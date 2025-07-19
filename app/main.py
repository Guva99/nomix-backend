import logging
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update

from app.routers import auth
from app.routers.callback import router as callback_router
from app.services.bot import bot     # <- уже создан singleton

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = FastAPI()

FLUTTER_WEB_DIR = Path("/app/frontend/build/web")

# ---- только статика (CSS/JS/ico и т.п.) ----
app.mount("/static", StaticFiles(directory=str(FLUTTER_WEB_DIR)), name="static")

# ---- ваши роутеры ----
app.include_router(auth.router)
app.include_router(callback_router)

# ---- lifecycle ----
@app.on_event("startup")
async def _on_startup() -> None:
    logger.info("FastAPI startup → init bot + webhook")
    await bot.initialize()
    await bot.setup_webhook("https://mixfom2025.fvds.ru/webhook")
    await bot.application.start()           # PTB-loop

# ---- Telegram webhook ----
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        payload = await request.json()
        upd = Update.de_json(payload, bot.application.bot)
        await bot.process_update(upd)
        return {"ok": True}
    except Exception as exc:                # noqa: BLE001
        logger.exception("webhook error")
        return {"ok": False, "error": str(exc)}

# ---- SPA fallback (отдаём index.html) ----
@app.get("/{_:path}")
async def spa_entry(request: Request):
    if request.url.path.startswith("/api"):
        raise HTTPException(status_code=404)

    index = FLUTTER_WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(500, "Flutter build missing")

    return FileResponse(index)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
