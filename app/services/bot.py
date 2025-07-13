import asyncio
import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Включаем логирование
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("Telegram Bot Token is missing!")

WEBAPP_LINK = "https://t.me/NomixAI_bot/nomix_ai"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received start command from {update.message.from_user.username}")
    await update.message.reply_text("Привет! Я бот Numix. Используй /login для входа.")
    logger.info("Replied to /start command.")


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received login command from {update.message.from_user.username}")
    await update.message.reply_text(f"Чтобы авторизоваться через Telegram Web App, нажми:\n{WEBAPP_LINK}")
    logger.info("Replied to /login command.")


def run_polling_in_thread(bot):
    # Этот метод будет запускать polling в синхронном режиме
    bot.run_polling()


async def start_bot():
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("login", login))
    await bot.initialize()

    loop = asyncio.get_event_loop()

    # Запускаем polling в отдельном потоке
    await loop.run_in_executor(None, run_polling_in_thread, bot)

    logger.info("Bot started successfully.")


async def on_startup():
    asyncio.create_task(start_bot())
