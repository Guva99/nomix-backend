import os
import logging
from typing import Optional
import base64
import httpx

from telegram import (
    Update,
    MenuButtonWebApp,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot
)
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

# ——— Настройка логирования ———
logger = logging.getLogger(__name__)

# ——— Переменные окружения ———
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

async def get_avatar_base64(user_id: int) -> str :
    try:
        bot = Bot(token=TOKEN)
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            return None

        # Берём самый большой размер
        file_obj = await bot.get_file(photos.photos[0][-1].file_id)
        path = file_obj.file_path  # может быть "photos/file_0.jpg" или полный URL

        # Правильно формируем URL
        if path.startswith("https://"):
            url = path
        else:
            url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"

        # Скачиваем
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logging.error(f"[get_avatar_base64] Failed to download {url}: {resp.status_code}")
                return None

            # Кодируем в Base64
            encoded = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"

    except Exception as e:
        logging.error(f"[get_avatar_base64] Failed for {user_id}: {e}")
        return None

class TelegramBot:
    """Singleton-обёртка вокруг python-telegram-bot v20"""

    def __init__(self) -> None:
        self.application: Optional[Application] = None

    async def initialize(self) -> None:
        if self.application:
            return

        # Создаём и конфигурируем приложение PTB
        self.application = ApplicationBuilder().token(TOKEN).build()

        # Версионированный URL для cache-busting
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"

        # Устанавливаем WebApp-кнопку в главное меню
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🚀 Открыть мини-приложение",
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        # Регистрируем команды
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("login", self._cmd_login))

        # Инициализируем внутренние механизмы библиотеки
        await self.application.initialize()
        logger.info("Telegram bot initialized")

    async def setup_webhook(self) -> None:
        await self.initialize()
        webhook_url = os.getenv("WEBHOOK_URL", f"{WEBAPP_BASE_URL}webhook")
        info = await self.application.bot.get_webhook_info()
        if info.url != webhook_url:
            await self.application.bot.set_webhook(
                url=webhook_url, drop_pending_updates=True
            )
            logger.info("Webhook configured: %s", webhook_url)
        else:
            logger.info("Webhook already at %s – skip", webhook_url)

    async def process_update(self, upd: Update) -> None:
        await self.initialize()
        await self.application.process_update(upd)

    # ——— Хендлеры команд ———

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("/start from %s", upd.effective_user.id)
        await upd.message.reply_text("Привет! Я бот Nomix. Используй /login для входа.")

    async def _cmd_login(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("/login from %s", upd.effective_user.id)
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        button = InlineKeyboardButton(
            text="🚀 Открыть мини-приложение",
            web_app=WebAppInfo(url=versioned_url),
        )
        keyboard = InlineKeyboardMarkup([[button]])
        await upd.message.reply_text(
            "Нажми на кнопку, чтобы открыть мини-приложение:", reply_markup=keyboard
        )

# Экспортируем синглтон
bot = TelegramBot()
