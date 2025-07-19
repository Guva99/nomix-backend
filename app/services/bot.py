import os
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_LINK = "https://t.me/NomixAI_bot/nomix_ai"


class TelegramBot:
    """Singleton-обёртка вокруг python-telegram-bot v20."""

    def __init__(self) -> None:
        self.application: Optional[Application] = None

    # ---------- infrastructure ----------

    async def initialize(self) -> None:
        if self.application:                      # уже инициализирован
            return

        self.application = (
            ApplicationBuilder()
            .token(TOKEN)
            .build()
        )

        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("login", self._cmd_login))

        await self.application.initialize()
        logger.info("Telegram bot initialised")

    async def setup_webhook(self, url: str) -> None:
        """Ставим webhook, если он ещё не установлен на нужный URL."""
        await self.initialize()

        info = await self.application.bot.get_webhook_info()
        if info.url != url:
            await self.application.bot.set_webhook(url=url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", url)
        else:
            logger.info("Webhook already points to %s – skip", url)

    async def process_update(self, upd: Update) -> None:
        """Отдаём update движку PTB."""
        await self.initialize()
        await self.application.process_update(upd)

    # ---------- command handlers ----------

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("/start from %s", upd.effective_user.id)
        await upd.message.reply_text("Привет! Я бот Numix. Используй /login для входа.")

    async def _cmd_login(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("/login from %s", upd.effective_user.id)
        await upd.message.reply_text(
            f"Чтобы авторизоваться через Telegram Web-App, нажми:\n{WEBAPP_LINK}"
        )


# экспортируем singleton
bot = TelegramBot()
