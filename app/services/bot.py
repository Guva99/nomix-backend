from __future__ import annotations
import os
import shutil
import logging
import base64
from urllib.parse import urlparse
import httpx
import json
import asyncio
from collections import defaultdict
from app.services.GPT import last_check_store

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    MenuButtonWebApp, WebAppInfo, InlineKeyboardButton,
    InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    CallbackQuery, Message
)
from aiogram.filters import Command, CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from html import escape

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
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🧾 Чек"), types.KeyboardButton(text="📈 Статистика")],
            [types.KeyboardButton(text="❓ Все команды")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
    return keyboard


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
                body += f" {i}. {name:<22} {price:,.2f} ₽\n"
            body += "—————————\n"

    footer = "\n•••••••••••••••••••••••••\n"
    footer += f"💰 Итого: {total:,.2f} ₽"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", web_app=WebAppInfo(url="https://nomix-d6199.web.app/approve"))],
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_save")],
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
        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None

    async def initialize(self) -> None:
        if self.bot:
            return

        self.bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()

        # Регистрация обработчиков
        self.dp.message.register(self._cmd_start, CommandStart())
        self.dp.message.register(self._cmd_save, Command("save"))
        self.dp.callback_query.register(self._on_callback_confirm_save, F.data == "confirm_save")
        self.dp.callback_query.register(self._on_menu_selection)
        self.dp.message.register(self._handle_photo, F.photo)
        self.dp.message.register(self._handle_text_buttons, F.text & ~F.command)

        # Настройка меню
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=versioned_url))
        )

        logger.info("Telegram bot initialized")

    async def setup_webhook(self) -> None:
        await self.initialize()
        webhook_url = os.getenv("WEBHOOK_URL", f"{WEBAPP_BASE_URL}webhook")

        webhook_info = await self.bot.get_webhook_info()
        if webhook_info.url != webhook_url:
            await self.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", webhook_url)
        else:
            logger.info("Webhook already at %s – skip", webhook_url)

    async def process_update(self, update: dict) -> None:
        await self.initialize()
        if self.dp:
            await self.dp.feed_update(self.bot, types.Update(**update))

    # ====== UI ======
    def _build_menu(self, exclude: list[str] | None = None) -> InlineKeyboardMarkup:
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

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def _cmd_start(self, message: Message):
        await message.answer(
            text="Выбери опцию (кнопки под полем ввода):",
            reply_markup=reply_keyboard(),
        )

    async def _handle_text_buttons(self, message: Message):
        text = (message.text or "").strip().lower()

        if "чек" in text:
            waiting_for_photo.add(message.from_user.id)
            await message.answer("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
        elif "статист" in text:
            await message.answer("📈 Раздел в разработке.", reply_markup=reply_keyboard())
        elif "команд" in text:
            await message.answer(
                "Доступно: 🧾 Чек, 📈 Статистика, /save — сохранить последний чек.",
                reply_markup=reply_keyboard()
            )
        else:
            await message.answer("Не понял. Нажми кнопку ниже 👇", reply_markup=reply_keyboard())

    async def _on_menu_selection(self, query: CallbackQuery):
        user_id = query.from_user.id

        try:
            await query.answer()

            if query.data == "stats":
                await query.message.answer("Эта опция ещё в разработке.", reply_markup=reply_keyboard())
            elif query.data == "send_receipt":
                waiting_for_photo.add(user_id)
                await query.message.answer("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())

                await asyncio.sleep(60)
                if user_id in waiting_for_photo:
                    waiting_for_photo.remove(user_id)
                    await self.bot.send_message(
                        chat_id=user_id,
                        text="⏱ Жду фото. Вернёмся в меню?",
                        reply_markup=reply_keyboard()
                    )
            elif query.data == "back_to_menu":
                waiting_for_photo.discard(user_id)
                await query.message.answer("🔙 Главное меню:", reply_markup=reply_keyboard())
            else:
                await query.message.answer("Выбери опцию:", reply_markup=reply_keyboard())

        except Exception as e:
            if "Query is too old" in str(e):
                await query.message.answer(
                    "⏱ Время на ответ истекло. Нажми кнопку снова.",
                    reply_markup=reply_keyboard()
                )
            else:
                logger.error(f"Ошибка обработки callback query: {e}")
                await query.message.answer("❌ Произошла ошибка. Попробуйте снова.", reply_markup=reply_keyboard())

    # ====== Сохранение ======
    async def _on_callback_confirm_save(self, query: CallbackQuery):
        await self._cmd_save(query.message, is_callback=True)

    async def _cmd_save(self, message: Message, is_callback: bool = False):
        user_id = message.from_user.id
        st = last_check_store.get(user_id)
        target = message

        if not st:
            await target.answer("❌ Нет распознанного чека для сохранения.", reply_markup=reply_keyboard())
            return

        # ------- определить имя файла и исходный путь -------
        image_url = (st.get("image_url") or "").strip()
        filename = (st.get("image_filename") or "").strip()

        # 1) если filename не передали — достанем из URL
        if not filename:
            try:
                path_part = urlparse(image_url).path
                filename = os.path.basename(path_part.rstrip("/"))
            except Exception:
                filename = ""

        # 2) если всё ещё пусто/‘tmp’ — найдём самый свежий temp-файл пользователя
        def find_latest_tmp(prefix_dir: str) -> str | None:
            if not os.path.isdir(prefix_dir):
                return None

            candidates = [
                f for f in os.listdir(prefix_dir)
                if f.startswith(f"user_{user_id}_") and os.path.isfile(os.path.join(prefix_dir, f))
            ]

            if not candidates:
                return None

            candidates.sort(key=lambda f: os.path.getmtime(os.path.join(prefix_dir, f)), reverse=True)
            return candidates[0]

        if not filename or filename.lower() == "tmp":
            filename = find_latest_tmp(RECEIPTS_TMP_NEW) or find_latest_tmp(RECEIPTS_TMP_OLD) or filename

        if not filename or filename.lower() == "tmp":
            await target.answer(
                "🚫 Не удалось определить файл изображения для сохранения. Попробуй отправить чек ещё раз.",
                reply_markup=reply_keyboard(),
            )
            return

        # Возможные места, где лежит временный файл
        src_candidates = [
            os.path.join(RECEIPTS_TMP_NEW, filename),  # /app/static/receipts/tmp/<file>
            os.path.join(RECEIPTS_TMP_OLD, filename),  # /app/static/tmp/<file> (старый путь)
        ]

        # Куда перемещаем
        final_path = os.path.join(RECEIPTS_ROOT, filename)

        # 3) если файл уже лежит в конечной папке — просто используем его
        if os.path.isfile(final_path):
            moved = True
        else:
            # ищем исходник среди кандидатов
            src_path = next((p for p in src_candidates if os.path.isfile(p)), None)
            moved = False

            if src_path:
                try:
                    os.makedirs(RECEIPTS_ROOT, exist_ok=True)  # безопасно для разных ФС
                    shutil.move(src_path, final_path)
                    moved = True
                except Exception as e:
                    logger.error("move image failed: %s", e, exc_info=True)
            else:
                logger.warning("Temp file not found for %s (candidates: %s)", filename, src_candidates)

        if not moved:
            await target.answer(
                "🚫 Не удалось перенести изображение из временной папки. Попробуй ещё раз.",
                reply_markup=reply_keyboard(),
            )
            return

        # Обновим URL на «боевой»
        # подменим любой tmp-сегмент на /static/receipts/
        good_url = image_url or ""
        if "/static/receipts/tmp/" in good_url:
            good_url = good_url.replace("/static/receipts/tmp/", "/static/receipts/")
        elif "/static/tmp/" in good_url:
            good_url = good_url.replace("/static/tmp/", "/static/receipts/")

        # если URL пустой или странный — сформируем его заново
        if not good_url or good_url.endswith("/tmp") or good_url.endswith("/tmp/"):
            good_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"

        st["image_url"] = good_url
        st["image_filename"] = filename  # заодно положим имя файла в стор

        # ------- сохранить чек в БД через API -------
        try:
            # поддерживаем оба формата: {"receipt": {...}} и плоский словарь
            raw_receipt = st.get("receipt") if isinstance(st, dict) and "receipt" in st else st

            if not isinstance(raw_receipt, dict):
                await target.answer(
                    "🚫 Формат данных чека неверный. Пришли фото ещё раз.",
                    reply_markup=reply_keyboard()
                )
                return

            payload = {**raw_receipt, "user_id": user_id}
            logger.info("[save] payload: %s", json.dumps(payload, ensure_ascii=False))

            async with httpx.AsyncClient() as client:
                save_resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/receipts/save-check",
                    json=payload
                )

                if save_resp.status_code != 200:
                    # компактное извлечение причины
                    brief = f"HTTP {save_resp.status_code}"
                    try:
                        j = save_resp.json()
                        logger.info("[save] 422 detail: %s", json.dumps(j, ensure_ascii=False))

                        if isinstance(j, dict) and "detail" in j:
                            det = j["detail"]
                            if isinstance(det, list):
                                parts = []
                                for e in det:
                                    loc = ".".join(str(x) for x in (e.get("loc") or []))
                                    msg = e.get("msg") or e.get("type") or ""
                                    parts.append(f"{loc}: {msg}")
                                brief = "; ".join(parts) or brief
                            else:
                                brief = str(det)
                        else:
                            txt_json = json.dumps(j, ensure_ascii=False)
                            brief = (txt_json[:900] + "…") if len(txt_json) > 900 else txt_json
                    except Exception:
                        txt = save_resp.text.strip()
                        brief = (txt[:900] + "…") if len(txt) > 900 else txt

                    await target.answer(
                        f"🚫 Не удалось сохранить чек.\n{brief}",
                        reply_markup=reply_keyboard()
                    )
                    return

        except Exception as e:
            logger.error("[save] unexpected error: %s", e, exc_info=True)
            await target.answer(
                "🚫 Произошла ошибка при сохранении чека.",
                reply_markup=reply_keyboard()
            )
            return

        # сюда попадём только при успешном сохранении
        await target.answer("✅ Чек сохранён!", reply_markup=reply_keyboard())

    # ====== Фото чека ======
    async def _handle_photo(self, message: Message):
        try:
            user_id = message.from_user.id
            waiting_for_photo.discard(user_id)

            photo = message.photo[-1]
            file = await self.bot.get_file(photo.file_id)
            path = file.file_path
            file_url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

            await message.answer("🔍 Чек получен. Начинаю обработку...", reply_markup=reply_keyboard())

            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/bot/process-check",
                    json={"file_url": file_url, "user_id": user_id},
                )

                if resp.status_code != 200:
                    await message.answer("❌ Произошла ошибка при обработке чека.",
                                         reply_markup=reply_keyboard())
                    return

                data = resp.json()
                result = data.get("result")

                if not result:
                    await message.answer("❌ Пустой результат от сервера.", reply_markup=reply_keyboard())
                    return

                if not result.get("is_receipt", False):
                    reason = result.get("reason", "Не удалось определить, что на изображении.")
                    await message.answer(f"🚫 Это не чек.\nПричина: {reason}", reply_markup=reply_keyboard())
                    return

                text, keyboard = render_receipt_message(result, user_id)
                await message.answer(escape(text), reply_markup=keyboard)

        except Exception:
            logger.exception("Ошибка при обработке фото")
            await message.answer("🚫 Произошла ошибка при обработке изображения.", reply_markup=reply_keyboard())


bot = TelegramBot()