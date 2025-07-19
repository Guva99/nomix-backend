import os
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, ContextTypes
)

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_LINK = "https://t.me/NomixAI_bot/nomix_ai"


class TelegramBot:
    """
    ОДИН единственный экземпляр бота на всё приложение.
    """
    def __init__(self) -> None:
        self.application: Optional[Application] = None

    # ---------- infrastructure ---------- #
    async def initialize(self) -> None:
        if self.application:               # уже инициализировали
            return

        self.application = (
            ApplicationBuilder()
            .token(TOKEN)
            .build()
        )

        # Хэндлеры команд
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("login", self._cmd_login))

        # Обязательный шаг PTB-20
        await self.application.initialize()
        logger.info("Telegram bot initialised")

    async def setup_webhook(self, url: str) -> None:
        """
        Ставим webhook, но только если он ещё не стоит.
        """
        await self.initialize()

        info = await self.application.bot.get_webhook_info()
        if info.url != url:
            await self.application.bot.set_webhook(
                url=url,
                drop_pending_updates=True,
            )
            logger.info("Webhook configured: %s", url)
        else:
            logger.info("Webhook already points to %s – skip", url)

    async def process_update(self, upd: Update) -> None:
        """
        Передаём апдейт в `telegram.ext.Application`.
        """
        await self.initialize()
        await self.application.process_update(upd)

    # ---------- command handlers ---------- #
    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("CMD /start from %s", update.effective_user.id)
        await update.message.reply_text(
            "Привет! Я бот Numix. Используй /login для входа."
        )

    async def _cmd_login(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("CMD /login from %s", update.effective_user.id)
        await update.message.reply_text(
            f"Чтобы авторизоваться через Telegram Web-App, нажми:\n{WEBAPP_LINK}"
        )


# экспортируем singleton
bot = TelegramBot()
