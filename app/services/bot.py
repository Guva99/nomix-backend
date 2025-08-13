from __future__ import annotations

import os
import shutil
import logging
import base64
import httpx
import json
import asyncio
from collections import defaultdict

from app.services.GPT import last_check_store
from telegram.helpers import escape
from telegram.error import BadRequest

from telegram import (
    Update,
    MenuButtonWebApp,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

# Файловые пути (оба внутри одного тома)
RECEIPTS_ROOT = "/app/static/receipts"
RECEIPTS_TMP_NEW = os.path.join(RECEIPTS_ROOT, "tmp")
RECEIPTS_TMP_OLD = "/app/static/tmp"  # поддержим старую схему на всякий случай
os.makedirs(RECEIPTS_ROOT, exist_ok=True)
os.makedirs(RECEIPTS_TMP_NEW, exist_ok=True)

# 🔄 Храним ID пользователей, от которых ждём фото
waiting_for_photo = set()


def reply_keyboard() -> ReplyKeyboardMarkup:
    # Кнопки под полем ввода (как на твоих скринах)
    return ReplyKeyboardMarkup(
        keyboard=[
            ["🧾 Чек", "📈 Статистика"],
            ["❓ Все команды"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


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
        "Прочее": "📦",
    }

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
            body += "—————————\n"

    footer = "\n•••••••••••••••••••••••••\n"
    footer += f"💰 Итого:              {total:,.2f} ₽"

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Редактировать", web_app=WebAppInfo(url="https://nomix-d6199.web.app/approve"))],
            [InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")],
        ]
    )
    return header + body + footer, keyboard


async def get_avatar_base64(user_id: int) -> str | None:
    try:
        bot = Bot(token=TOKEN)
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            return None

        file_obj = await bot.get_file(photos.photos[0][-1].file_id)
        path = file_obj.file_path
        url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

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
    def __init__(self) -> None:
        self.application: Application | None = None

    async def initialize(self) -> None:
        if self.application:
            return

        self.application = ApplicationBuilder().token(TOKEN).build()

        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        # маленькая кнопка слева у поля ввода
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=versioned_url))
        )

        # команды
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("save", self._cmd_save))  # вручную сохранить последний чек

        # callback'и
        self.application.add_handler(CallbackQueryHandler(self._on_callback_confirm_save, pattern="^confirm_save$"))
        self.application.add_handler(CallbackQueryHandler(self._on_menu_selection))

        # входящие
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_text_buttons))

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

    # ====== UI ======
    def _build_menu(self, exclude: list[str] | None = None) -> InlineKeyboardMarkup:
        # оставим на всякий случай (используется в старых местах)
        if exclude is None:
            exclude = []
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        buttons = []
        if "app" not in exclude:
            buttons.append(
                [
                    InlineKeyboardButton(text="📱 Отрыть приложение", web_app=WebAppInfo(url=versioned_url)),
                ]
            )
        row = []
        if "stats" not in exclude:
            row.append(InlineKeyboardButton(text="📈 Статистика", callback_data="stats"))
        if "send_receipt" not in exclude:
            row.append(InlineKeyboardButton(text="🧾 Чек", callback_data="send_receipt"))
        if row:
            buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await ctx.bot.send_message(
            chat_id=upd.effective_chat.id,
            text="Выбери опцию (кнопки под полем ввода):",
            reply_markup=reply_keyboard(),
        )

    async def _handle_text_buttons(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = (upd.message.text or "").strip().lower()
        if "чек" in text:
            waiting_for_photo.add(upd.effective_user.id)
            await upd.message.reply_text("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
        elif "статист" in text:
            await upd.message.reply_text("📈 Раздел в разработке.", reply_markup=reply_keyboard())
        elif "команд" in text:
            await upd.message.reply_text(
                "Доступно: 🧾 Чек, 📈 Статистика, /save — сохранить последний чек.", reply_markup=reply_keyboard()
            )
        else:
            await upd.message.reply_text("Не понял. Нажми кнопку ниже 👇", reply_markup=reply_keyboard())

    async def _on_menu_selection(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = upd.callback_query
        user_id = query.from_user.id
        try:
            await query.answer()

            if query.data == "stats":
                await query.message.reply_text("Эта опция ещё в разработке.", reply_markup=reply_keyboard())

            elif query.data == "send_receipt":
                waiting_for_photo.add(user_id)
                await query.message.reply_text("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
                await asyncio.sleep(60)
                if user_id in waiting_for_photo:
                    waiting_for_photo.remove(user_id)
                    await ctx.bot.send_message(
                        chat_id=user_id, text="⏱ Жду фото. Вернёмся в меню?", reply_markup=reply_keyboard()
                    )

            elif query.data == "back_to_menu":
                waiting_for_photo.discard(user_id)
                await query.message.reply_text("🔙 Главное меню:", reply_markup=reply_keyboard())

            else:
                await query.message.reply_text("Выбери опцию:", reply_markup=reply_keyboard())

        except BadRequest as e:
            if "Query is too old" in str(e):
                await query.message.reply_text(
                    "⏱ Время на ответ истекло. Нажми кнопку снова.", reply_markup=reply_keyboard()
                )
            else:
                logger.error(f"Ошибка обработки callback query: {e}")
                await query.message.reply_text("❌ Произошла ошибка. Попробуйте снова.", reply_markup=reply_keyboard())

    # ====== Сохранение ======
    async def _on_callback_confirm_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self._cmd_save(upd, ctx)

    async def _cmd_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # работает и для /save, и для инлайн-кнопки
        user_id = upd.effective_user.id if upd.effective_user else upd.callback_query.from_user.id
        st = last_check_store.get(user_id)
        target = upd.message if getattr(upd, "message", None) else upd.callback_query.message

        if not st:
            await target.reply_text("❌ Нет распознанного чека для сохранения.", reply_markup=reply_keyboard())
            return

        # Попробуем перевести временный файл из tmp -> receipts
        try:
            image_url = st.get("image_url") or ""
            filename = os.path.basename(image_url)

            # возможные источники
            candidates = [
                os.path.join(RECEIPTS_TMP_NEW, filename),  # /app/static/receipts/tmp/xxx.jpg
                os.path.join(RECEIPTS_TMP_OLD, filename),  # /app/static/tmp/xxx.jpg (старый путь)
            ]
            src_path = next((p for p in candidates if p and os.path.exists(p)), None)
            if src_path:
                dst_path = os.path.join(RECEIPTS_ROOT, filename)
                os.makedirs(RECEIPTS_ROOT, exist_ok=True)
                shutil.move(src_path, dst_path)  # безопасно для разных ФС
                # обновим URL
                st["image_url"] = (
                    image_url.replace("/static/receipts/tmp/", "/static/receipts/")
                    .replace("/static/tmp/", "/static/receipts/")
                )

        except Exception as e:
            logger.error("move image failed: %s", e, exc_info=True)
            await target.reply_text(
                "🚫 Не удалось сохранить файл изображения. Попробуйте ещё раз.", reply_markup=reply_keyboard()
            )
            return

        # сохраним чек в бэкенд
        try:
            payload = {**st, "user_id": user_id}
            async with httpx.AsyncClient() as client:
                save_resp = await client.post("https://mixfom2025.fvds.ru/api/receipts/save-check", json=payload)
            if save_resp.status_code != 200:
                detail = save_resp.text
                try:
                    detail = save_resp.json().get("detail") or detail
                except Exception:
                    pass
                await target.reply_text(f"🚫 Не удалось сохранить чек.\n\n{detail}", reply_markup=reply_keyboard())
                return
        except Exception as e:
            logger.exception("[save] http error: %s", e)
            await target.reply_text("🚫 Ошибка при сохранении. Попробуйте позже.", reply_markup=reply_keyboard())
            return

        await target.reply_text("✅ Чек сохранён!", reply_markup=reply_keyboard())

    # ====== Фото чека ======
    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = upd.effective_user.id
            waiting_for_photo.discard(user_id)

            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)

            path = file.file_path
            file_url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"
            await upd.message.reply_text("🔍 Чек получен. Начинаю обработку...", reply_markup=reply_keyboard())

            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/bot/process-check",
                    json={"file_url": file_url, "user_id": user_id},
                )

            if resp.status_code != 200:
                await upd.message.reply_text("❌ Произошла ошибка при обработке чека.", reply_markup=reply_keyboard())
                return

            data = resp.json()
            result = data.get("result")
            if not result:
                await upd.message.reply_text("❌ Пустой результат от сервера.", reply_markup=reply_keyboard())
                return

            if not result.get("is_receipt", False):
                reason = result.get("reason", "Не удалось определить, что на изображении.")
                await upd.message.reply_text(f"🚫 Это не чек.\nПричина: {reason}", reply_markup=reply_keyboard())
                return

            text, keyboard = render_receipt_message(result, user_id)
            await upd.message.reply_text(escape(text), reply_markup=keyboard, parse_mode="HTML")

        except Exception:
            logger.exception("Ошибка при обработке фото")
            await upd.message.reply_text("🚫 Произошла ошибка при обработке изображения.", reply_markup=reply_keyboard())


bot = TelegramBot()
