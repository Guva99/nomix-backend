import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("Telegram Bot Token is missing!")
    raise ValueError("Telegram Bot Token is missing!")

WEBAPP_LINK = "https://t.me/NomixAI_bot/nomix_ai"


class TelegramBot:
    def __init__(self):
        self.application = None

    async def initialize(self):
        """Инициализация бота и обработчиков команд"""
        self.application = Application.builder().token(TOKEN).build()

        # Регистрация обработчиков команд
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("login", self.login))

        await self.application.initialize()
        logger.info("Bot initialized")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        logger.info(f"Received start command from {update.effective_user.username}")
        await update.message.reply_text(
            "Привет! Я бот Numix. Используй /login для входа."
        )

    async def login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /login"""
        logger.info(f"Received login command from {update.effective_user.username}")
        await update.message.reply_text(
            f"Чтобы авторизоваться через Telegram Web App, нажми:\n{WEBAPP_LINK}"
        )

    async def setup_webhook(self, webhook_url: str):
        """Установка вебхука"""
        if not self.application:
            await self.initialize()

        await self.application.bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        logger.info(f"Webhook set up at {webhook_url}")

    async def process_update(self, update_data: dict):
        """Обработка входящего обновления"""
        if not self.application:
            await self.initialize()

        update = Update.de_json(update_data, self.application.bot)
        await self.application.process_update(update)


# Создаем экземпляр бота для использования в других модулях
bot = TelegramBot()


async def on_startup():
    """Функция для запуска при старте FastAPI"""
    webhook_url = f"https://mixfom2025.fvds.ru/webhook"  # Замените на реальный URL
    await bot.setup_webhook(webhook_url)