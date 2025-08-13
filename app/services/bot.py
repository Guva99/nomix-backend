import os
import logging
import base64
import httpx
import json
import asyncio
from collections import defaultdict
from telegram.helpers import escape
from telegram.error import BadRequest
from telegram import (
    Update, MenuButtonWebApp, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, Bot, BotCommand
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from app.services.GPT import last_check_store

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

PUBLIC_STATIC_BASE = "https://mixfom2025.fvds.ru/static/receipts"
STATIC_RECEIPT_DIR = "/app/static/receipts"

waiting_for_photo = set()

def render_receipt_text(receipt: dict) -> str:
    store = receipt.get("store", "Магазин")
    date = receipt.get("date", "")
    time = receipt.get("time", "")
    total = receipt.get("total", 0.0)

    header = f"🛒 {store} — {date} {time}\n\n"

    categories = defaultdict(lambda: defaultdict(list))
    for item in receipt.get("items", []):
        cat = item.get("category", "Прочее")
        subcat = item.get("subcategory") or "—"
        categories[cat][subcat].append((item["name"], item["price"]))

    category_emojis = {"Продукты":"🍔","Заведение":"🍽","Еда и напитки":"🍔","Здоровье":"💊","Транспорт":"🚗","Шопинг":"🛍","Прочее":"📦"}

    body = ""
    for cat, subcats in categories.items():
        emoji = category_emojis.get(cat, "📦")
        cat_sum = sum(sum(price for _, price in items) for items in subcats.values())
        body += f"{emoji} {cat} — {cat_sum:,.2f} ₽\n"
        for subcat, items in subcats.items():
            subcat_sum = sum(price for _, price in items)
            body += f"  {subcat}: {subcat_sum:,.2f} ₽\n"
    footer = f"\n💰 Итого: {total:,.2f} ₽"
    return header + body + footer

class TelegramBot:
    def __init__(self) -> None:
        self.application: Application = None

    async def initialize(self) -> None:
        if self.application:
            return
        self.application = ApplicationBuilder().token(TOKEN).build()

        # мини‑апп — короткая подпись
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open",  # короче и не «кричит»
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        # команды в меню (иконка 9‑квадратиков)
        await self.application.bot.set_my_commands([
            BotCommand("start", "Начать"),
            BotCommand("receipt", "Отправить фото чека"),
            BotCommand("save", "Сохранить последний распознанный чек"),
            BotCommand("cancel", "Отменить и удалить последний чек"),
            BotCommand("stats", "Статистика"),
        ])

        # хендлеры
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("receipt", self._cmd_receipt))
        self.application.add_handler(CommandHandler("save", self._cmd_save))
        self.application.add_handler(CommandHandler("cancel", self._cmd_cancel))
        self.application.add_handler(CommandHandler("stats", self._cmd_stats))

        # больше НЕ используем confirm_save и тяжелые inline‑кнопки
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self.application.initialize()
        logger.info("Telegram bot initialized")

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

    # --- команды ---

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await ctx.bot.send_message(
            chat_id=upd.effective_chat.id,
            text="Привет! Используй меню команд (кнопка с квадратами) или:\n" \
                 "/receipt — прислать фото чека\n/save — сохранить последний\n/cancel — отменить"
        )

    async def _cmd_stats(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("Статистика пока в разработке.")

    async def _cmd_receipt(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        waiting_for_photo.add(user_id)
        await upd.message.reply_text("📸 Пришли фото чека одним сообщением. После распознавания я попрошу подтвердить /save или /cancel.")
        # мягкое напоминание
        await asyncio.sleep(60)
        if user_id in waiting_for_photo:
            waiting_for_photo.discard(user_id)
            await ctx.bot.send_message(chat_id=user_id, text="⏱ Не дождался фото. Команда /receipt чтобы попробовать снова.")

    async def _cmd_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        data = last_check_store.get(user_id)
        if not data:
            await upd.message.reply_text("❌ Нет распознанного чека для сохранения.")
            return

        receipt = data.get("receipt") or {}
        tmp_path = data.get("tmp_path")
        tmp_name = data.get("tmp_name")
        if not tmp_path or not os.path.exists(tmp_path):
            await upd.message.reply_text("❌ Временный файл изображения не найден.")
            last_check_store.pop(user_id, None)
            return

        # переносим файл в публичную статику
        final_path = os.path.join(STATIC_RECEIPT_DIR, tmp_name)
        try:
            os.replace(tmp_path, final_path)  # атомарнее чем rename на некоторых FS
        except Exception as e:
            logger.exception("move image failed: %s", e)
            await upd.message.reply_text("🚫 Не удалось сохранить изображение на сервере.")
            return

        image_url = f"{PUBLIC_STATIC_BASE}/{tmp_name}"
        payload = {**receipt, "user_id": user_id, "image_url": image_url}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post("https://mixfom2025.fvds.ru/api/receipts/save-check", json=payload)
            if resp.status_code != 200:
                detail = resp.text
                try:
                    detail = resp.json().get("detail") or detail
                except Exception:
                    pass
                await upd.message.reply_text(f"🚫 Не удалось сохранить чек.\n{detail}")
                # откат: удалим файл, чтобы не копился мусор
                try: os.remove(final_path)
                except Exception: pass
                return
        except Exception:
            logger.exception("save-check request failed")
            # откат файла
            try: os.remove(final_path)
            except Exception: pass
            await upd.message.reply_text("🚫 Ошибка сети при сохранении.")
            return

        last_check_store.pop(user_id, None)
        await upd.message.reply_text(f"✅ Чек сохранён.\n🖼 {image_url}")

    async def _cmd_cancel(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        data = last_check_store.pop(user_id, None)
        if data:
            tmp_path = data.get("tmp_path")
            if tmp_path and os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass
        await upd.message.reply_text("❎ Ок, не сохраняю. Можешь прислать новый чек через /receipt.")

    # --- сообщения/фото ---

    async def _handle_message(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # обычные тексты не команды
        await upd.message.reply_text("Используй меню команд или /receipt чтобы прислать фото чека.")

    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = upd.effective_user.id
            waiting_for_photo.discard(user_id)

            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            path = file.file_path
            file_url = path if path.startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

            await upd.message.reply_text("🔍 Чек получен. Обрабатываю...")

            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/bot/process-check",
                    json={"file_url": file_url, "user_id": user_id}
                )

            if resp.status_code != 200:
                await upd.message.reply_text("❌ Ошибка при обработке чека.")
                return

            data = resp.json()
            result = data.get("result")
            if not result:
                await upd.message.reply_text("❌ Пустой результат от сервера.")
                return

            if not result.get("is_receipt", False):
                reason = result.get("reason", "Не смог распознать чек на фото.")
                await upd.message.reply_text(f"🚫 Это не чек. Причина: {reason}")
                return

            text = render_receipt_text(result)
            await upd.message.reply_text(escape(text) + "\n\nЧтобы сохранить — команда /save, чтобы отменить — /cancel.", parse_mode="HTML")

        except Exception:
            logger.exception("Ошибка при обработке фото")
            await upd.message.reply_text("🚫 Произошла ошибка при обработке изображения.")

bot = TelegramBot()
