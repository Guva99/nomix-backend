import os, logging
from typing import Optional
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_LINK = "https://t.me/NomixAI_bot/nomix_ai"


class TelegramBot:
    def __init__(self) -> None:
        self.application: Optional[ApplicationBuilder] = None

    async def initialize(self) -> None:
        if self.application:
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
        await self.initialize()
        info = await self.application.bot.get_webhook_info()
        if info.url != url:
            await self.application.bot.set_webhook(url=url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", url)

    async def process_update(self, upd: Update) -> None:
        await self.initialize()
        await self.application.process_update(upd)

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("Привет! Я бот Numix. Используй /login для входа.")

    async def _cmd_login(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text(
            f"Чтобы авторизоваться через Telegram Web-App, нажми:\n{WEBAPP_LINK}"
        )


bot = TelegramBot()
