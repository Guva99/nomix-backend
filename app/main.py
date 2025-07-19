import logging
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from telegram import Update

from app.routers import auth
from app.routers.callback import router as callback_router
from app.services.bot import bot     # ← singleton, уже создан

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)

# ---------- FastAPI skeleton ----------
app = FastAPI()
FLUTTER_WEB_DIR = Path("/app/frontend/build/web")
templates = Jinja2Templates(directory="/app/frontend/templates")

# static (сам Flutter-билд)
app.mount("/static",  StaticFiles(directory=str(FLUTTER_WEB_DIR)), name="static")
app.mount("/",        StaticFiles(directory=str(FLUTTER_WEB_DIR), html=True),
          name="flutter")

# routers
app.include_router(auth.router)
app.include_router(callback_router)

# ---------- lifecycle ----------
@app.on_event("startup")
async def _on_startup() -> None:
    logger.info("FastAPI startup → init bot + webhook")
    await bot.initialize()
    await bot.setup_webhook("https://mixfom2025.fvds.ru/webhook")
    await bot.application.start()          # запускаем PTB-loop

# ---------- Telegram webhook ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Получаем JSON от Telegram, перегоняем в `telegram.Update`
    и скармливаем PTB.
    """
    try:
        data = await request.json()
        upd = Update.de_json(data, bot.application.bot)
        await bot.process_update(upd)
        return {"ok": True}
    except Exception as exc:               # noqa: BLE001
        logger.exception("Webhook error")
        return {"ok": False, "error": str(exc)}

# ---------- SPA fall-back ----------
@app.get("/{_:path}")
async def spa_entry(request: Request):
    """
    Любой путь (кроме /webhook и /api) отдаём как index.html,
    чтобы работал client-side‐router GoRouter.
    """
    # не лезем на энд-пойнты API
    if request.url.path.startswith("/api"):
        raise HTTPException(status_code=404)

    index = FLUTTER_WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(500, "Flutter build missing")
    return FileResponse(index)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
