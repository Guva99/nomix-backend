from __future__ import annotations

import os
import logging
import base64
import json
import asyncio
from collections import defaultdict
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    MenuButtonWebApp, WebAppInfo, InlineKeyboardButton,
    InlineKeyboardMarkup, ReplyKeyboardMarkup,
    CallbackQuery, Message
)
from aiogram.filters import Command, CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from html import escape

from app.services.GPT import last_check_store

logger = logging.getLogger(__name__)

# ------------ Config ------------

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

API_BASE = os.getenv("API_BASE_URL", "https://mixfom2025.fvds.ru")
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", f"{API_BASE}/api/telegram/webhook")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "")

PROCESS_CHECK_URL = f"{API_BASE}/api/bot/process-check"
SAVE_CHECK_URL = f"{API_BASE}/api/receipts/save-check"

# 🔄 кого ждём с фото
waiting_for_photo: set[int] = set()


# ------------ UI helpers ------------

def reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🧾 Чек"), types.KeyboardButton(text="📈 Статистика")],
            [types.KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def render_receipt_message(receipt: dict, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    store = receipt.get("store", "Магазин")
    date = receipt.get("date", "")
    time = receipt.get("time", "")
    total = float(receipt.get("total", 0.0))

    header = f"🛒 {store} — {date} {time}\n\n"

    categories = defaultdict(lambda: defaultdict(list))
    for item in receipt.get("items", []):
        cat = item.get("category", "Прочее")
        subcat = item.get("subcategory") or "—"
        name = item.get("name", "—")
        price = float(item.get("price", 0.0))
        categories[cat][subcat].append((name, price))

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
        body += f"{emoji} {cat} — {cat_sum:,.2f} ₽\n\n"
        for subcat, items in subcats.items():
            subcat_sum = sum(price for _, price in items)
            body += f"{subcat}: {subcat_sum:,.2f} ₽\n"
            for i, (name, price) in enumerate(items, 1):
                body += f"  {i}. {name:<22} {price:,.2f} ₽\n"
            body += "—————————\n"

    footer = "\n•••••••••••••••••••••••••\n"
    footer += f"💰 Итого: {total:,.2f} ₽"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", web_app=WebAppInfo(url="https://nomix-d6199.web.app/approve"))],
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_save")],
        ]
    )
    return header + body + footer, kb


# ------------ Bot ------------

class TelegramBot:
    def __init__(self) -> None:
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._reminders: dict[int, asyncio.Task] = {}

    # --- infra ---

    async def initialize(self) -> None:
        if self.bot:
            return
        self.bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()

        # единый httpx клиент
        headers = {"X-Internal-Secret": INTERNAL_API_SECRET} if INTERNAL_API_SECRET else {}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0), headers=headers)

        # Хэндлеры
        self.dp.message.register(self._cmd_start, CommandStart())
        self.dp.message.register(self._cmd_save, Command("save"))
        self.dp.callback_query.register(self._on_callback_confirm_save, F.data == "confirm_save")
        self.dp.callback_query.register(self._on_menu_selection)
        self.dp.message.register(self._handle_photo, F.photo)
        self.dp.message.register(self._handle_text_buttons, F.text & ~F.command)

        # Кнопка mini-app
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть приложение", web_app=WebAppInfo(url=versioned_url))
        )
        logger.info("Telegram bot initialized")

    async def setup_webhook(self) -> None:
        await self.initialize()

        # Сначала удаляем старый вебхук
        try:
            await self.bot.delete_webhook(drop_pending_updates=True)
            logger.info("🗑 Old webhook deleted")
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to delete old webhook: {e}")

        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        try:
            # Устанавливаем вебхук с правильными параметрами
            result = await self.bot.set_webhook(
                url=WEBHOOK_URL,
                drop_pending_updates=True,  # важно поставить True
                secret_token=secret,
                allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
                max_connections=40,
                ip_address=None,  # пусть Telegram сам определяет IP
            )
            logger.info(f"✅ Webhook set to {WEBHOOK_URL}, result: {result}")

            # Проверяем информацию о вебхуке
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"📋 Webhook info: {webhook_info}")

        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
            raise

    async def process_update(self, update: dict) -> None:
        await self.initialize()

        # Логируем получение обновления
        update_id = update.get('update_id')
        logger.info(f"📨 Received update: {update_id}")

        if self.dp:
            await self.dp.feed_update(self.bot, types.Update(**update))

    # --- helpers ---

    async def _send(self, chat_id: int, text: str, markup: Optional[InlineKeyboardMarkup | ReplyKeyboardMarkup] = None):
        try:
            await self.bot.send_message(chat_id, text, reply_markup=markup or reply_keyboard())
        except Exception:
            logger.exception("[send] failed")

    async def _schedule_reminder(self, user_id: int, delay_sec: int = 60):
        # отменяем прошлый таймер для юзера
        old = self._reminders.pop(user_id, None)
        if old and not old.done():
            old.cancel()

        async def _task():
            try:
                await asyncio.sleep(delay_sec)
                if user_id in waiting_for_photo:
                    waiting_for_photo.discard(user_id)
                    await self._send(user_id, "⏱ Жду фото. Вернёмся в меню?")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[reminder] error: {e}")

        self._reminders[user_id] = asyncio.create_task(_task())

    def _build_menu(self, exclude: list[str] | None = None) -> InlineKeyboardMarkup:
        if exclude is None:
            exclude = []
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        buttons = []
        if "app" not in exclude:
            buttons.append([InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=versioned_url))])
        row = []
        if "stats" not in exclude:
            row.append(InlineKeyboardButton(text="📈 Статистика", callback_data="stats"))
        if "send_receipt" not in exclude:
            row.append(InlineKeyboardButton(text="🧾 Чек", callback_data="send_receipt"))
        if row:
            buttons.append(row)
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def get_avatar_base64(self, user_id: int) -> str | None:
        try:
            photos = await self.bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count == 0:
                return None
            file_obj = await self.bot.get_file(photos.photos[0][-1].file_id)
            path = file_obj.file_path
            url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

            assert self._client is not None
            resp = await self._client.get(url)
            if resp.status_code != 200:
                logger.error(f"[get_avatar_base64] download failed {url}: {resp.status_code}")
                return None
            encoded = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
        except Exception as e:
            logger.error(f"[get_avatar_base64] Failed for {user_id}: {e}")
            return None

    # --- commands & callbacks ---

    async def _cmd_start(self, message: Message):
        await message.answer(
            text="Привет! Я Nomix — помощник по анализу чеков. Выбери опцию ниже, чтобы начать:",
            reply_markup=reply_keyboard(),
        )

    async def _handle_text_buttons(self, message: Message):
        text = (message.text or "").strip().lower()
        if "чек" in text:
            waiting_for_photo.add(message.from_user.id)
            await message.answer("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
            await self._schedule_reminder(message.from_user.id)
        elif "статист" in text:
            await message.answer("📈 Раздел в разработке.", reply_markup=reply_keyboard())
        elif "команд" in text:
            await message.answer("Доступно: 🧾 Чек, 📈 Статистика, /save — сохранить последний чек.", reply_markup=reply_keyboard())
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
                await self._schedule_reminder(user_id)
            elif query.data == "back_to_menu":
                waiting_for_photo.discard(user_id)
                # отменим таймер
                t = self._reminders.pop(user_id, None)
                if t and not t.done():
                    t.cancel()
                await query.message.answer("🔙 Главное меню:", reply_markup=reply_keyboard())
            else:
                await query.message.answer("Выбери опцию:", reply_markup=reply_keyboard())
        except Exception as e:
            if "Query is too old" in str(e):
                await query.message.answer("⏱ Время на ответ истекло. Нажми кнопку снова.", reply_markup=reply_keyboard())
            else:
                logger.error(f"Ошибка обработки callback query: {e}")
                await query.message.answer("❌ Произошла ошибка. Попробуйте снова.", reply_markup=reply_keyboard())

    # --- long tasks (background) ---

    async def _process_check_background(self, chat_id: int, file_url: str, user_id: int):
        try:
            assert self._client is not None
            resp = await self._client.post(PROCESS_CHECK_URL, json={"file_url": file_url, "user_id": user_id})
            if resp.status_code != 200:
                await self._send(chat_id, "❌ Произошла ошибка при обработке чека.")
                return

            data = resp.json()
            result = data.get("result")
            if not result:
                await self._send(chat_id, "❌ Пустой результат от сервера.")
                return

            if not result.get("is_receipt", False):
                reason = result.get("reason", "Не удалось определить, что на изображении.")
                await self._send(chat_id, f"🚫 Это не чек.\nПричина: {reason}")
                return

            text, keyboard = render_receipt_message(result, user_id)
            await self.bot.send_message(chat_id, escape(text), reply_markup=keyboard)

        except Exception:
            logger.exception("[_process_check_background] error")
            await self._send(chat_id, "🚫 Произошла ошибка при обработке изображения.")

    async def _save_check_background(self, chat_id: int, user_id: int):
        try:
            st = last_check_store.get(user_id)
            if not st:
                await self._send(chat_id, "❌ Нет распознанного чека для сохранения.")
                return

            # Normalize staged payload
            if "receipt" in st:
                raw_receipt = dict(st["receipt"])
                if "tmp_name" in st:
                    raw_receipt["tmp_name"] = st["tmp_name"]
                if "tmp_path" in st:
                    raw_receipt["tmp_path"] = st["tmp_path"]
            else:
                raw_receipt = dict(st)

            payload = {**raw_receipt, "user_id": user_id}
            payload.pop("tmp_name", None)
            payload.pop("tmp_path", None)
            if not payload.get("image_url") and "tmp_name" in raw_receipt:
                payload["image_url"] = f"/static/tmp/{raw_receipt['tmp_name']}"

            logger.info("[save-bg] payload: %s", json.dumps(payload, ensure_ascii=False))

            assert self._client is not None
            save_resp = await self._client.post(SAVE_CHECK_URL, json=payload)

            if save_resp.status_code != 200:
                brief = f"HTTP {save_resp.status_code}"
                try:
                    j = save_resp.json()
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

                await self._send(chat_id, f"🚫 Не удалось сохранить чек.\n{brief}")
                return

            # success → чистим временное
            if user_id in last_check_store:
                del last_check_store[user_id]
                logger.info(f"🧹 [save-bg] Временные данные очищены для user_id={user_id}")

            await self._send(chat_id, "✅ Чек сохранён!")

        except Exception:
            logger.exception("[_save_check_background] error")
            await self._send(chat_id, "🚫 Произошла ошибка при сохранении чека.")

    # --- triggers -> background ---

    async def _on_callback_confirm_save(self, query: CallbackQuery):
        try:
            await query.answer()
        except Exception:
            pass
        await query.message.answer("💾 Сохраняю чек…", reply_markup=reply_keyboard())
        asyncio.create_task(self._save_check_background(query.message.chat.id, query.message.chat.id))

    async def _cmd_save(self, message: Message, is_callback: bool = False):
        user_id = message.chat.id if is_callback else message.from_user.id
        if user_id not in last_check_store:
            await message.answer("❌ Нет распознанного чека для сохранения.", reply_markup=reply_keyboard())
            return
        await message.answer("💾 Сохраняю чек…", reply_markup=reply_keyboard())
        asyncio.create_task(self._save_check_background(message.chat.id, user_id))

    async def _handle_photo(self, message: Message):
        try:
            user_id = message.from_user.id
            waiting_for_photo.discard(user_id)

            # Отменяем таймер
            t = self._reminders.pop(user_id, None)
            if t and not t.done():
                t.cancel()

            # НЕМЕДЛЕННЫЙ ответ пользователю
            await message.answer("🔍 Чек получен. Начинаю обработку…",
                                 reply_markup=reply_keyboard())

            # Получаем информацию о файле асинхронно
            photo = message.photo[-1]
            file = await self.bot.get_file(photo.file_id)
            path = file.file_path
            file_url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"
            asyncio.create_task(
                self._process_check_background(message.chat.id, file_url, user_id)
            )

        except Exception as e:
            logger.error(f"Ошибка при обработке фото: {e}")
            await message.answer("🚫 Произошла ошибка при обработке изображения.",
                                 reply_markup=reply_keyboard())


bot = TelegramBot()
