import os
import logging
import base64
import json
import asyncio
import shutil
from collections import defaultdict

import httpx
from telegram.helpers import escape
from telegram.error import BadRequest
from telegram import (
    Update,
    MenuButtonWebApp,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Bot,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.services.GPT import last_check_store

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

# Файлы (tmp теперь в receipts → один и тот же docker volume)
STATIC_DIR = "/app/static"
RECEIPTS_DIR = os.path.join(STATIC_DIR, "receipts")
TMP_DIR = os.path.join(RECEIPTS_DIR, "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

# Состояния
waiting_for_photo: set[int] = set()

# ----- ВСПОМОГАТЕЛЬНОЕ -----
def _reply_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("📸 Сканировать чек")],
        [KeyboardButton("✅ Сохранить чек"), KeyboardButton("📈 Статистика")],
        [KeyboardButton("❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

def render_receipt_message(receipt: dict, user_id: int) -> str:
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

    em = {
        "Продукты": "🍔", "Заведение": "🍽", "Еда и напитки": "🍔",
        "Здоровье": "💊", "Транспорт": "🚗", "Шопинг": "🛍", "Прочее": "📦"
    }

    body = ""
    for cat, subcats in categories.items():
        cat_sum = sum(sum(p for _, p in items) for items in subcats.values())
        body += f"{em.get(cat, '📦')} {cat}::::{cat_sum:,.2f}₽\n\n"
        for subcat, items in subcats.items():
            sub_sum = sum(p for _, p in items)
            body += f"{subcat} === {sub_sum:,.2f} ₽\n"
            for i, (name, price) in enumerate(items, 1):
                body += f"  {i}. {name:<22} {price:,.2f} ₽\n"
            body += "—————————\n"

    footer = "\n•••••••••••••••••••••••••\n" + f"💰 Итого:              {total:,.2f} ₽"
    return header + body + footer

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
                logger.error(f"[get_avatar_base64] download fail {url}: {resp.status_code}")
                return None
            encoded = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        logger.error(f"[get_avatar_base64] failed for {user_id}: {e}")
        return None

# ----- КЛАСС БОТА -----
class TelegramBot:
    def __init__(self) -> None:
        self.application: Application = None

    async def initialize(self) -> None:
        if self.application:
            return
        self.application = ApplicationBuilder().token(TOKEN).build()

        # Маленькая синяя кнопка “Open”
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open",  # подпись у системной кнопки; на iOS/Android всё равно маленькая синяя
                web_app=WebAppInfo(url=versioned_url),
            )
        )

        # Команды (для меню “Все команды”)
        await self.application.bot.set_my_commands([
            ("start", "Старт / меню"),
            ("save", "Сохранить последний чек"),
            ("help", "Помощь"),
        ])

        # Хэндлеры
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("save", self._cmd_save))
        self.application.add_handler(CommandHandler("help", self._cmd_help))
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

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

    # ----- Команды -----
    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        waiting_for_photo.discard(upd.effective_user.id)
        await ctx.bot.send_message(
            chat_id=upd.effective_chat.id,
            text="Выбери действие на клавиатуре ниже 👇",
            reply_markup=_reply_kb(),
        )

    async def _cmd_help(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text(
            "📸 «Сканировать чек» — пришлите фото.\n"
            "✅ «Сохранить чек» — сохранит последний распознанный чек.\n"
            "📈 «Статистика» — скоро.\n",
            reply_markup=_reply_kb(),
        )

    async def _cmd_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        data = last_check_store.get(user_id)
        if not data:
            await upd.message.reply_text("❌ Нет распознанного чека для сохранения.", reply_markup=_reply_kb())
            return

        # Если в кеше хранится tmp-файл — переносим его в receipts
        tmp_path = data.get("_tmp_path")
        public_url = data.get("image_url")

        if tmp_path and os.path.exists(tmp_path):
            try:
                filename = os.path.basename(tmp_path)
                final_path = os.path.join(RECEIPTS_DIR, filename)
                # shutil.move безопасно обработает EXDEV (copy+unlink)
                shutil.move(tmp_path, final_path)
                public_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"
                data["image_url"] = public_url
                data.pop("_tmp_path", None)
            except Exception as e:
                logger.error(f"move image failed: {e}", exc_info=True)
                await upd.message.reply_text("🚫 Не удалось сохранить файл чека.", reply_markup=_reply_kb())
                return

        # Отправляем на /save-check
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/receipts/save-check",
                    json={**data, "user_id": user_id},
                )
            if resp.status_code != 200:
                detail = resp.text
                try:
                    detail = resp.json().get("detail") or detail
                except Exception:
                    pass
                await upd.message.reply_text(f"🚫 Не удалось сохранить чек.\n\n{detail}", reply_markup=_reply_kb())
                return
        except Exception as e:
            logger.exception("save-check request failed: %s", e)
            await upd.message.reply_text("🚫 Ошибка сети при сохранении.", reply_markup=_reply_kb())
            return

        await upd.message.reply_text("✅ Чек сохранён!", reply_markup=_reply_kb())

    # ----- Текстовая клавиатура -----
    async def _handle_text(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = (upd.message.text or "").strip().lower()
        if "скан" in text or "чек" in text:
            return await self._ask_for_photo(upd, ctx)
        if "сохран" in text:
            return await self._cmd_save(upd, ctx)
        if "статист" in text:
            return await upd.message.reply_text("Эта опция ещё в разработке.", reply_markup=_reply_kb())
        return await self._cmd_help(upd, ctx)

    async def _ask_for_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = upd.effective_user.id
        waiting_for_photo.add(user_id)
        await upd.message.reply_text("📸 Пришлите фото чека.", reply_markup=_reply_kb())

        # напоминание через 60 сек
        await asyncio.sleep(60)
        if user_id in waiting_for_photo:
            waiting_for_photo.remove(user_id)
            await ctx.bot.send_message(chat_id=user_id,
                                       text="⏱ Вы не прислали фото. Готов помочь, как будете готовы.",
                                       reply_markup=_reply_kb())

    # ----- Фото -----
    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = upd.effective_user.id
            waiting_for_photo.discard(user_id)

            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            path = file.file_path
            file_url = path if path.startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

            await upd.message.reply_text("🔍 Обрабатываю чек…", reply_markup=_reply_kb())

            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/bot/process-check",
                    json={"file_url": file_url, "user_id": user_id},
                )

            if resp.status_code != 200:
                await upd.message.reply_text("❌ Ошибка при обработке чека.", reply_markup=_reply_kb())
                return

            data = resp.json().get("result")
            if not data:
                await upd.message.reply_text("❌ Пустой результат от сервера.", reply_markup=_reply_kb())
                return

            # Если backend вернул путь временного файла — сохраним (ожидаем, что /process-check кладёт сюда)
            # Смотри, чтобы routers/gpt.py писал в TMP_DIR и возвращал ключ '_tmp_path'
            # Пример: result["_tmp_path"] = "/app/static/receipts/tmp/user_...jpg"
            text = "🚫 Это не чек."
            if data.get("is_receipt", False):
                text = escape(render_receipt_message(data, user_id))
            last_check_store[user_id] = data

            await upd.message.reply_text(text, reply_markup=_reply_kb(), parse_mode="HTML")

        except Exception:
            logger.exception("Ошибка при обработке фото")
            await upd.message.reply_text("🚫 Произошла ошибка при обработке изображения.", reply_markup=_reply_kb())


bot = TelegramBot()
