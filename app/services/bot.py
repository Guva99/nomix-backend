import os
import logging
import httpx
import json
import asyncio
import base64
from collections import defaultdict
from typing import Optional

from telegram import (
    Update,
    MenuButtonWebApp,
    WebAppInfo,
    Bot,
    BotCommand,
)
from telegram.helpers import escape
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

# --- конфиг из ENV ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("env TELEGRAM_BOT_TOKEN not set")

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://mixfom2025.fvds.ru/api/telegram/")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

# где лежат итоговые картинки (публичная статика)
PUBLIC_STATIC_BASE = "https://mixfom2025.fvds.ru/static/receipts"
STATIC_RECEIPT_DIR = "/app/static/receipts"

# --- вспомогательные вещи ---

async def get_avatar_base64(user_id: int) -> Optional[str]:
    """
    Скачивает аватар пользователя и возвращает data: URL (base64) или None.
    """
    try:
        tgbot = Bot(token=TOKEN)
        photos = await tgbot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            return None

        file_obj = await tgbot.get_file(photos.photos[0][-1].file_id)
        path = file_obj.file_path
        url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.error(f"[get_avatar_base64] Failed to download {url}: {resp.status_code}")
                return None

        encoded = base64.b64encode(resp.content).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        logger.error(f"[get_avatar_base64] Failed for {user_id}: {e}")
        return None


def render_receipt_text(receipt: dict) -> str:
    """Короткое человекочитаемое резюме распознанного чека."""
    store = receipt.get("store", "Магазин")
    date = receipt.get("date", "")
    time = receipt.get("time", "")
    total = receipt.get("total", 0.0)

    header = f"🛒 {store} — {date} {time}\n\n"

    categories = defaultdict(lambda: defaultdict(list))
    for item in receipt.get("items", []):
        cat = item.get("category", "Прочее")
        subcat = item.get("subcategory") or "—"
        categories[cat][subcat].append((item.get("name", "—"), float(item.get("price", 0))))

    category_emojis = {
        "Продукты": "🍔",
        "Заведение": "🍽",
        "Еда и напитки": "🍔",
        "Здоровье": "💊",
        "Транспорт": "🚗",
        "Шопинг": "🛍",
        "Прочее": "📦",
    }

    body_lines = []
    for cat, subcats in categories.items():
        emoji = category_emojis.get(cat, "📦")
        cat_sum = sum(sum(price for _, price in items) for items in subcats.values())
        body_lines.append(f"{emoji} {cat}: {cat_sum:,.2f} ₽")
        for subcat, items in subcats.items():
            subcat_sum = sum(price for _, price in items)
            body_lines.append(f"  • {subcat}: {subcat_sum:,.2f} ₽")

    footer = f"\n💰 Итого: {float(total):,.2f} ₽"
    return header + ("\n".join(body_lines) if body_lines else "—") + footer


class TelegramBot:
    """
    Обёртка над python-telegram-bot:
    - создаёт меню команд
    - ставит компактную кнопку мини‑аппа "Open"
    - обрабатывает /receipt, /save, /cancel, /stats и фото
    - совместим с main.py через глобальную переменную `bot`
    """

    def __init__(self) -> None:
        self.application: Optional[Application] = None

    # --- жизненный цикл/инициализация ---

    async def initialize(self) -> None:
        if self.application:
            return

        self.application = ApplicationBuilder().token(TOKEN).build()

        # компактная кнопка мини‑аппа (не засоряет интерфейс)
        versioned_url = f"{WEBAPP_BASE_URL}?v={BUILD_VERSION}"
        await self.application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=versioned_url))
        )

        # команды в меню
        await self.application.bot.set_my_commands(
            [
                BotCommand("start", "Начать"),
                BotCommand("receipt", "Отправить фото чека"),
                BotCommand("save", "Сохранить последний распознанный чек"),
                BotCommand("cancel", "Отменить и удалить последний чек"),
                BotCommand("stats", "Статистика"),
            ]
        )

        # handlers
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("stats", self._cmd_stats))
        self.application.add_handler(CommandHandler("receipt", self._cmd_receipt))
        self.application.add_handler(CommandHandler("save", self._cmd_save))
        self.application.add_handler(CommandHandler("cancel", self._cmd_cancel))

        # фото -> распознаём чек
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        # текст без команд — мягкая подсказка
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self.application.initialize()
        logger.info("Telegram bot initialized")

    async def setup_webhook(self) -> None:
        """Вызывается из app.main при старте сервиса."""
        await self.initialize()
        webhook_url = os.getenv("WEBHOOK_URL", f"{WEBAPP_BASE_URL}webhook")
        info = await self.application.bot.get_webhook_info()
        if info.url != webhook_url:
            await self.application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Webhook configured: %s", webhook_url)
        else:
            logger.info("Webhook already at %s – skip", webhook_url)

    async def process_update(self, upd: Update) -> None:
        """Хэнд-офф из роутера вебхука."""
        await self.initialize()
        await self.application.process_update(upd)

    # --- команды ---

    async def _cmd_start(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await ctx.bot.send_message(
            chat_id=upd.effective_chat.id,
            text=(
                "Привет! Я помогу разобрать чек по категориям.\n\n"
                "Команды:\n"
                "• /receipt — пришли фото чека\n"
                "• /save — сохранить последний распознанный чек\n"
                "• /cancel — удалить последний распознанный чек\n"
                "• /stats — статистика (скоро)\n\n"
                "Также в меню есть кнопка Open для мини‑аппа."
            ),
        )

    async def _cmd_stats(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("Статистика пока в разработке.")

    async def _cmd_receipt(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("📸 Отправь фото чека одним сообщением. После распознавания подтверди /save или /cancel.")

    async def _cmd_save(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Подтверждение сохранения: переносим файл из tmp -> receipts, шлём в /save-check."""
        user_id = upd.effective_user.id
        data = last_check_store.get(user_id)
        if not data:
            await upd.message.reply_text("❌ Нет распознанного чека для сохранения. Используй /receipt и отправь фото.")
            return

        # ожидаем, что в last_check_store лежит:
        # {"receipt": {...}, "tmp_path": ".../tmp_xxx.jpg", "tmp_name": "xxx.jpg"}
        receipt = data.get("receipt") or {}
        tmp_path = data.get("tmp_path")
        tmp_name = data.get("tmp_name")
        if not tmp_path or not tmp_name or not os.path.exists(tmp_path):
            last_check_store.pop(user_id, None)
            await upd.message.reply_text("❌ Временный файл изображения не найден. Пришли чек ещё раз через /receipt.")
            return

        final_path = os.path.join(STATIC_RECEIPT_DIR, tmp_name)
        try:
            os.replace(tmp_path, final_path)
        except Exception as e:
            logger.exception("move image failed: %s", e)
            await upd.message.reply_text("🚫 Не удалось сохранить изображение на сервере.")
            return

        image_url = f"{PUBLIC_STATIC_BASE}/{tmp_name}"
        payload = {**receipt, "user_id": user_id, "image_url": image_url}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post("https://mixfom2025.fvds.ru/api/receipts/save-check", json=payload)
            if r.status_code != 200:
                detail = r.text
                try:
                    detail = r.json().get("detail") or detail
                except Exception:
                    pass
                try:
                    os.remove(final_path)
                except Exception:
                    pass
                await upd.message.reply_text(f"🚫 Не удалось сохранить чек.\n{detail}")
                return
        except Exception:
            logger.exception("save-check request failed")
            try:
                os.remove(final_path)
            except Exception:
                pass
            await upd.message.reply_text("🚫 Ошибка сети при сохранении. Попробуй позже.")
            return

        last_check_store.pop(user_id, None)
        await upd.message.reply_text(f"✅ Чек сохранён.\n🖼 {image_url}")

    async def _cmd_cancel(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Отмена: удаляем временный файл и очищаем память."""
        user_id = upd.effective_user.id
        data = last_check_store.pop(user_id, None)
        if data:
            tmp_path = data.get("tmp_path")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        await upd.message.reply_text("❎ Ок, не сохраняю. Можешь прислать новый чек через /receipt.")

    # --- произвольные сообщения/фото ---

    async def _handle_message(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await upd.message.reply_text("Используй /receipt чтобы прислать фото чека, затем /save или /cancel.")

    async def _handle_photo(self, upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Приходит фото — пересылаем его бэку на /api/bot/process-check."""
        try:
            user_id = upd.effective_user.id
            photo = upd.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            path = file.file_path
            file_url = path if str(path).startswith("https://") else f"https://api.telegram.org/file/bot{TOKEN}/{path}"

            await upd.message.reply_text("🔍 Чек получен. Обрабатываю...")

            timeout = httpx.Timeout(120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://mixfom2025.fvds.ru/api/bot/process-check",
                    json={"file_url": file_url, "user_id": user_id},
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

            # ожидаем, что /process-check положил во временное хранилище структуру с tmp_*,
            # либо сам result уже содержит, а роутер сделал сохранение в last_check_store.
            # Здесь ничего не трогаем — просто просим подтвердить.
            await upd.message.reply_text(
                escape(text) + "\n\nЧтобы сохранить — /save, чтобы отменить — /cancel.",
                parse_mode="HTML",
            )

        except Exception:
            logger.exception("Ошибка при обработке фото")
            await upd.message.reply_text("🚫 Произошла ошибка при обработке изображения. Попробуй ещё раз.")

# экспорт для main.py
bot = TelegramBot()
