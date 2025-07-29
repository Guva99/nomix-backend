import os
import logging
import base64
import httpx
import json

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
    MessageHandler,
    ContextTypes,
    filters
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

        self.application = ApplicationBuilder().token(TOKEN).build()

        # WebApp кнопка в меню
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📱 Отрыть приложение",
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        # Хендлеры
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CallbackQueryHandler(self._on_menu_selection))
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

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
        chat_id = upd.effective_chat.id
        try:
            with open("asset/welcome.gif", "rb") as gif:
                await ctx.bot.send_animation(
                    chat_id=chat_id,
                    animation=gif,
                    caption="Привет! Я Nomix — твой помощник по учёту трат 🧮"
                )
        except FileNotFoundError:
            await ctx.bot.send_message(chat_id=chat_id, text="Привет! Я Nomix — твой помощник по учёту трат 🧮")

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

    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = upd.effective_user.id
            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)

            path = file.file_path
            if path.startswith("https://"):
                file_url = path  # если уже полный
            else:
                file_url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
            await upd.message.reply_text("🔍 Чек получен. Начинаю обработку...")

            # Отправка в backend
            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    resp = await client.post("https://mixfom2025.fvds.ru/api/bot/process-check", json={
                        "file_url": file_url,
                        "user_id": user_id
                    })
                except httpx.ReadTimeout:
                    logger.error("[BOT] Таймаут при обращении к backend")
                    await upd.message.reply_text("⏱️ Сервер слишком долго обрабатывает изображение. Попробуйте позже.")
                    return

            if resp.status_code != 200:
                logger.error(f"[BOT] Ошибка от backend: {resp.status_code}, response: {resp.text}")
                await upd.message.reply_text("❌ Произошла ошибка при обработке чека.")
                return

            try:
                data = resp.json()
            except Exception as e:
                logger.exception("[BOT] Не удалось распарсить JSON от backend")
                await upd.message.reply_text("❌ Backend вернул невалидный JSON.")
                return

            raw_result = data.get("result")
            if not raw_result:
                logger.error("[BOT] Пустой result от backend")
                await upd.message.reply_text("❌ Пустой результат от сервера.")
                return

            try:
                result = json.loads(raw_result)
            except json.JSONDecodeError:
                logger.error(f"[BOT] Невалидный JSON от GPT: {raw_result}")
                await upd.message.reply_text("❌ Ответ от GPT не является валидным JSON.")
                return

            if not result.get("is_receipt", False):
                reason = result.get("reason", "Не удалось определить, что на изображении.")
                await upd.message.reply_text(f"🚫 Это не чек.\nПричина: {reason}")
                return

            store = result.get("store", "неизвестный магазин")
            total = result.get("total", "?")
            date = result.get("date", "")
            time = result.get("time", "")
            await upd.message.reply_text(
                f"✅ Чек из *{store}*\n🗓 {date} {time}\n💰 Сумма: {total}₽",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.exception("Ошибка при обработке фото")
            await upd.message.reply_text("🚫 Произошла ошибка при обработке изображения.")


# Экспортируем синглтон
bot = TelegramBot()
