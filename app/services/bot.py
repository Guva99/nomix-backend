import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

WEBAPP_LINK = "https://t.me/NumixStartBot/nomix_ai"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот Numix. Используй /login для входа."
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Чтобы авторизоваться через Telegram Web App, нажми:\n{WEBAPP_LINK}"
    )

async def start_bot():
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("login", login))
    await bot.initialize()
    await bot.start()
    print("Бот запущен!")

async def on_startup():
    await start_bot()
