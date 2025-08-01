import os
import logging
import base64
import httpx
import json
import re
import asyncio
from collections import defaultdict
from app.services.GPT import last_check_store

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

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

waiting_for_photo = set()

def render_receipt_message(receipt: dict, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    store = receipt.get("store", "Магазин")
    date = receipt.get("date", "")
    time = receipt.get("time", "")
    total = receipt.get("total", 0.0)

    header = f"🛒 {store} — {date} {time}\n\n"

    categories = defaultdict(lambda: defaultdict(list))
    for item in receipt["items"]:
        cat = item.get("category", "Прочее")
        subcat = item.get("subcategory") or "—"
        categories[cat][subcat].append((item["name"], item["price"]))

    category_emojis = {
        "Продукты": "🍔",
        "Заведение": "🍽",
        "Еда и напитки": "🍔",
        "Здоровье": "💊",
        "Транспорт": "🚗",
        "Шопинг": "🛍",
        "Прочее": "📦"
    }

    def fmt_line(label: str, value: float, pad: int = 24) -> str:
        return f"{label:<{pad}} {value:,.2f} ₽"

    body = ""
    for cat, subcats in categories.items():
        emoji = category_emojis.get(cat, "📦")
        cat_sum = sum(sum(price for _, price in items) for items in subcats.values())
        body += f"{emoji} {cat}::::{cat_sum:,.2f}₽\n\n"

        for subcat, items in subcats.items():
            subcat_sum = sum(price for _, price in items)
            body += f"{subcat} === {subcat_sum:,.2f} ₽\n"
            for i, (name, price) in enumerate(items, 1):
                body += f"  {i}. {name:<22} {price:,.2f} ₽\n"
            body += "———————————\n"

    footer = "\n••••••••••••••••••••••\n"
    footer += f"💰 Итого:              {total:,.2f} ₽"

    message = header + body + footer

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Редактировать", web_app=WebAppInfo(url="https://nomix-d6199.web.app/approve")),
            InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")
        ]
    ])
    return message, keyboard


class TelegramBot:
    def __init__(self):
        self.application: Application = None

    async def initialize(self):
        if self.application:
            return

        self.application = ApplicationBuilder().token(TOKEN).build()

        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📱 Отрыть приложение",
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CallbackQueryHandler(self._on_menu_selection))
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT, self._handle_message))
        self.application.add_handler(CallbackQueryHandler(self._on_callback_confirm_save, pattern="^confirm_save$"))
        self.application.add_handler(CallbackQueryHandler(self._on_menu_selection))

        await self.application.initialize()
        logger.info("Telegram bot initialized")

    async def setup_webhook(self):
        await self.initialize()
        webhook_url = os.getenv("WEBHOOK_URL", f"{WEBAPP_BASE_URL}webhook")
        info = await self.application.bot.get_webhook_info()
        if info.url != webhook_url:
            await self.application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", webhook_url)
        else:
            logger.info("Webhook already at %s – skip", webhook_url)

    async def process_update(self, upd: Update):
        await self.initialize()
        await self.application.process_update(upd)

    def _build_menu(self, exclude: list[str] = None) -> InlineKeyboardMarkup:
        if exclude is None:
            exclude = []
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        buttons = []
        if "app" not in exclude:
            buttons.append([InlineKeyboardButton(text="📱 Отрыть приложение", web_app=WebAppInfo(url=versioned_url))])
        row = []
        if "stats" not in exclude:
            row.append(InlineKeyboardButton(text="📈 Статистика", callback_data="stats"))
        if "send_receipt" not in exclude:
            row.append(InlineKeyboardButton(text="🧾 Чек", callback_data="send_receipt"))
        if row:
            buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await ctx.bot.send_message(chat_id=upd.effective_chat.id, text="Выбери опцию:", reply_markup=self._build_menu())

    async def _on_menu_selection(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = upd.callback_query
        await query.answer()
        if query.data == "stats":
            await query.message.reply_text("Эта опция ещё в разработке.", reply_markup=self._build_menu(exclude=["stats"]))
        elif query.data == "send_receipt":
            user_id = query.from_user.id
            waiting_for_photo.add(user_id)
            await query.message.reply_text("Пришли фото чека, и я разберу его по полочкам 🧲", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Вернуться в меню", callback_data="go_home")]]))
            await asyncio.sleep(60)
            if user_id in waiting_for_photo:
                waiting_for_photo.remove(user_id)
                await ctx.bot.send_message(chat_id=user_id, text="⏱ Время ожидания истекло. Вернёмся в начало?", reply_markup=self._build_menu())
        elif query.data == "go_home":
            await query.message.reply_text("Выбери опцию:", reply_markup=self._build_menu())

    async def _handle_message(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("📝 Я получил ваше сообщение!")

    async def _on_callback_confirm_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = upd.callback_query
        await query.answer()

        user_id = query.from_user.id
        try:
            if user_id not in last_check_store:
                await query.message.reply_text("❌ Нет распознанного чека для сохранения.")
                return

            last_check = last_check_store[user_id]
            async with httpx.AsyncClient() as client:
                save_resp = await client.post("https://mixfom2025.fvds.ru/api/bot/save-check", json={**last_check, "user_id": user_id})

            if save_resp.status_code != 200:
                try:
                    detail = save_resp.json().get("detail") or save_resp.text
                except Exception:
                    detail = save_resp.text
                await query.message.reply_text(f"🚫 Не удалось сохранить чек.\n\n{detail}")
                return

            await query.message.reply_text("✅ Чек успешно сохранён!")
        except Exception:
            logger.exception("Error saving check")
            await query.message.reply_text("🚫 Ошибка при сохранении. Попробуйте позже.")

    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        waiting_for_photo.discard(user_id)

        try:
            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            file_url = file.file_path if file.file_path.startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
            await upd.message.reply_text("🔍 Чек получен. Начинаю обработку...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post("https://mixfom2025.fvds.ru/api/bot/process-check", json={"file_url": file_url, "user_id": user_id})

            data = resp.json()
            result = data.get("result")
            if not result or not result.get("is_receipt"):
                await upd.message.reply_text("🚫 Это не чек.")
                return

            text, keyboard = render_receipt_message(result, user_id)
            await upd.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            logger.exception("Error in handle_photo")
            await upd.message.reply_text("🚫 Ошибка при обработке фото")


bot = TelegramBot()
