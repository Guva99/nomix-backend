import os
import logging
import shutil
import asyncio
from collections import defaultdict
from urllib.parse import urlparse
import base64

import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from app.services.GPT import last_check_store  # твой store

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

RECEIPTS_ROOT = "/app/static/receipts"
RECEIPTS_TMP_NEW = f"{RECEIPTS_ROOT}/tmp"
RECEIPTS_TMP_OLD = "/app/static/tmp"

os.makedirs(RECEIPTS_ROOT, exist_ok=True)
os.makedirs(RECEIPTS_TMP_NEW, exist_ok=True)

waiting_for_photo = set()

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ====== Клавиатуры ======
def reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            ["🧾 Чек", "📈 Статистика"],
            ["❓ Все команды"]
        ],
        resize_keyboard=True,
        persistent=True,
    )

def build_inline_keyboard(user_id: int):
    versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✏️ Редактировать", web_app=WebAppInfo(url=f"https://nomix-d6199.web.app/approve"))],
        [InlineKeyboardButton("✅ Сохранить", callback_data="confirm_save")]
    ])

# ====== Рендер чека ======
def render_receipt_message(receipt: dict, user_id: int):
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

    keyboard = build_inline_keyboard(user_id)
    return header + body + footer, keyboard

# ====== Команды ======
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Выбери опцию (кнопки под полем ввода):", reply_markup=reply_keyboard())

@dp.message(Command("save"))
async def cmd_save(message: types.Message):
    user_id = message.from_user.id
    st = last_check_store.get(user_id)
    if not st:
        await message.reply("❌ Нет распознанного чека для сохранения.", reply_markup=reply_keyboard())
        return
    await save_check(user_id, st, message)

# ====== Текстовые кнопки ======
@dp.message()
async def handle_text(message: types.Message):
    text = (message.text or "").lower()
    user_id = message.from_user.id
    if "чек" in text:
        waiting_for_photo.add(user_id)
        await message.reply("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
    elif "статист" in text:
        await message.reply("📈 Раздел в разработке.", reply_markup=reply_keyboard())
    elif "команд" in text:
        await message.reply("Доступно: 🧾 Чек, 📈 Статистика, /save — сохранить последний чек.", reply_markup=reply_keyboard())
    else:
        await message.reply("Не понял. Нажми кнопку ниже 👇", reply_markup=reply_keyboard())

# ====== Callback ======
@dp.callback_query()
async def handle_callback(query: types.CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    await query.answer()
    if data == "stats":
        await query.message.reply("📈 Эта опция ещё в разработке.", reply_markup=reply_keyboard())
    elif data == "send_receipt":
        waiting_for_photo.add(user_id)
        await query.message.reply("📸 Пришли фото чека — разберу его 🧮", reply_markup=reply_keyboard())
        await asyncio.sleep(60)
        if user_id in waiting_for_photo:
            waiting_for_photo.remove(user_id)
            await bot.send_message(user_id, "⏱ Жду фото. Вернёмся в меню?", reply_markup=reply_keyboard())
    elif data == "confirm_save":
        st = last_check_store.get(user_id)
        if st:
            await save_check(user_id, st, query.message)
    else:
        await query.message.reply("Выбери опцию:", reply_markup=reply_keyboard())

# ====== Фото ======
@dp.message(types.ContentType.PHOTO)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    waiting_for_photo.discard(user_id)
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"

    await message.reply("🔍 Чек получен. Начинаю обработку...", reply_markup=reply_keyboard())
    asyncio.create_task(process_check_background(file_url, user_id, message))

# ====== Фоновая обработка чека ======
async def process_check_background(file_url: str, user_id: int, message: types.Message):
    try:
        timeout = httpx.Timeout(120)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://mixfom2025.fvds.ru/api/bot/process-check",
                json={"file_url": file_url, "user_id": user_id},
            )

        data = resp.json()
        result = data.get("result")
        if not result:
            await message.reply("❌ Пустой результат от сервера.", reply_markup=reply_keyboard())
            return

        if not result.get("is_receipt", False):
            reason = result.get("reason", "Не удалось определить, что на изображении.")
            await message.reply(f"🚫 Это не чек.\nПричина: {reason}", reply_markup=reply_keyboard())
            return

        text, keyboard = render_receipt_message(result, user_id)
        await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

    except Exception:
        logger.exception("Ошибка при фоновой обработке чека")
        await message.reply("🚫 Произошла ошибка при обработке изображения.", reply_markup=reply_keyboard())

# ====== Сохранение чека ======
async def save_check(user_id: int, st: dict, message: types.Message):
    try:
        image_url = st.get("image_url") or ""
        filename = st.get("image_filename") or ""

        if not filename or filename.lower() == "tmp":
            # попробуем взять из tmp
            def find_latest_tmp(prefix_dir: str) -> None:
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

            filename = find_latest_tmp(RECEIPTS_TMP_NEW) or find_latest_tmp(RECEIPTS_TMP_OLD) or filename

        if not filename:
            await message.reply("🚫 Не удалось определить файл для сохранения.", reply_markup=reply_keyboard())
            return

        src_candidates = [
            os.path.join(RECEIPTS_TMP_NEW, filename),
            os.path.join(RECEIPTS_TMP_OLD, filename),
        ]
        final_path = os.path.join(RECEIPTS_ROOT, filename)
        if not os.path.isfile(final_path):
            src_path = next((p for p in src_candidates if os.path.isfile(p)), None)
            if src_path:
                shutil.move(src_path, final_path)
            else:
                await message.reply("🚫 Файл не найден в tmp.", reply_markup=reply_keyboard())
                return

        # формируем URL
        good_url = f"https://mixfom2025.fvds.ru/static/receipts/{filename}"
        st["image_url"] = good_url
        st["image_filename"] = filename

        # сохраняем через API
        raw_receipt = st.get("receipt") if "receipt" in st else st
        payload = {**raw_receipt, "user_id": user_id}
        logger.info("[save] payload: %s", payload)

        async with httpx.AsyncClient() as client:
            resp = await client.post("https://mixfom2025.fvds.ru/api/receipts/save-check", json=payload)

        if resp.status_code != 200:
            await message.reply(f"🚫 Не удалось сохранить чек. HTTP {resp.status_code}", reply_markup=reply_keyboard())
            return

        await message.reply("✅ Чек сохранён!", reply_markup=reply_keyboard())

    except Exception:
        logger.exception("Ошибка при сохранении чека")
        await message.reply("🚫 Произошла ошибка при сохранении.", reply_markup=reply_keyboard())

# ====== Настройка меню ======
async def setup_menu():
    versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
    await bot.set_chat_menu_button(MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=versioned_url)))
