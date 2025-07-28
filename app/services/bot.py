import os
import logging
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
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# ——— Настройка логирования ———
logger = logging.getLogger(__name__)

# ——— Переменные окружения ———
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

async def get_avatar_base64(user_id: int) -> str:
    try:
        bot = Bot(token=TOKEN)
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            return None

        file_obj = await bot.get_file(photos.photos[0][-1].file_id)
        path = file_obj.file_path

        url = path if path.startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.error(f"[get_avatar_base64] Failed to download {url}: {resp.status_code}")
                return None

            encoded = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        logger.error(f"[get_avatar_base64] Failed for {user_id}: {e}")
        return None


class TelegramBot:
    """Singleton-обёртка вокруг python-telegram-bot v20"""

    def __init__(self) -> None:
        self.application: Application = None

    async def initialize(self) -> None:
        if self.application:
            return

        # Создаём и конфигурируем приложение PTB
        self.application = ApplicationBuilder().token(TOKEN).build()

        # Устанавливаем укороченную WebApp-кнопку в меню чата
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📱 Отрыть приложение",
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        # Регистрируем команду /start и обработчик нажатий
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CallbackQueryHandler(self._on_menu_selection))

        await self.application.initialize()
        logger.info("Telegram bot initialized with short menu button text")

    async def setup_webhook(self) -> None:
        await self.initialize()
        webhook_url = os.getenv("WEBHOOK_URL", f"{WEBAPP_BASE_URL}webhook")
        info = await self.application.bot.get_webhook_info()
        if info.url != webhook_url:
            await self.application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", webhook_url)
        else:
            logger.info("Webhook already at %s – skip", webhook_url)

    async def process_update(self, upd: Update) -> None:
        await self.initialize()
        await self.application.process_update(upd)

    def _build_menu(self, exclude: list[str] = None) -> InlineKeyboardMarkup:
        if exclude is None:
            exclude = []
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        buttons = []
        if "app" not in exclude:
            buttons.append([InlineKeyboardButton(
                text="📱 Отрыть приложение",
                web_app=WebAppInfo(url=versioned_url)
            )])
        row = []
        if "stats" not in exclude:
            row.append(InlineKeyboardButton(text="📈 Статистика", callback_data="stats"))
        if "send_receipt" not in exclude:
            row.append(InlineKeyboardButton(text="🧾 Чек", callback_data="send_receipt"))
        if row:
            buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # text = ("Привет! Я Nomix — твой помощник по учёту трат. "
        #         "Выбери услугу:")
        # await upd.message.reply_text(text, reply_markup=self._build_menu())
        chat_id = upd.effective_chat.id

        # ✅ Отправляем локальный GIF как анимацию
        with open("asset/welcome.gif", "rb") as gif:
            await ctx.bot.send_animation(
                chat_id=chat_id,
                animation=gif,
                caption="Привет! Я Nomix — твой помощник по учёту трат 🧮"
            )
            await ctx.bot.send_message(
                chat_id=chat_id,
                text="Выбери опцию:",
                reply_markup=self._build_menu()
            )
    async def _on_menu_selection(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = upd.callback_query
        await query.answer()
        if query.data == "stats":
            await query.message.reply_text(
                "Эта опция ещё в разработке.",
                reply_markup=self._build_menu(exclude=["stats"])
            )
        elif query.data == "send_receipt":
            await query.message.reply_text(
                "Пришли фото чека, и я разберу его по полочкам 🧮",
                reply_markup=self._build_menu(exclude=["send_receipt"])
            )
        else:
            await query.message.reply_text(
                "Выбери опцию:",
                reply_markup=self._build_menu()
            )

# Экспортируем синглтон
bot = TelegramBot()
