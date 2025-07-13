import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.templating import Jinja2Templates
from routers import auth
from routers.callback import router as callback_router
from services.bot import bot, on_startup

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="/app/frontend/templates")

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(callback_router)

@app.on_event("startup")
async def startup():
    logger.info("Starting bot and FastAPI app...")
    await on_startup()

@app.post("/webhook")
async def webhook(request: Request):
    update_data = await request.json()
    await bot.process_update(update_data)
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    logger.info("Root endpoint accessed.")
    return templates.TemplateResponse("home.html", {"request": request})

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)