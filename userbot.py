import asyncio
import logging
import os
import random
import re
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv

import database as db

load_dotenv()

# === Конфигурация из .env ===
API_ID = int(os.getenv("API_ID", "1234567"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
SESSION_NAME = os.getenv("SESSION_NAME", "manager_session")

PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "1080"))

WORK_START_HOUR = int(os.getenv("WORK_START_HOUR", "8"))
WORK_END_HOUR = int(os.getenv("WORK_END_HOUR", "22"))
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "userbot.log")

# === Логирование ===
logger = logging.getLogger("userbot")
logger.setLevel(getattr(logging, LOG_LEVEL))

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Консольный хэндлер
console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

# Файловый хэндлер с ротацией
from logging.handlers import RotatingFileHandler
try:
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"Не удалось создать файловый логгер: {e}")


# === Pyrogram Client ===
client_kwargs = {
    "api_id": API_ID,
    "api_hash": API_HASH,
    "session_name": SESSION_NAME,
}

if PROXY_ENABLED and PROXY_HOST:
    client_kwargs["proxy"] = {
        "scheme": "socks5",
        "hostname": PROXY_HOST,
        "port": PROXY_PORT,
    }
    logger.info(f"Используется прокси: {PROXY_HOST}:{PROXY_PORT}")

app = Client(**client_kwargs)


# === Spintax с поддержкой вложенности ===
def parse_spintax(text: str) -> str:
    """
    Поддерживает вложенный spintax:
    {Привет|Здравствуйте|{Добрый день|Доброго времени суток}}
    """
    pattern = re.compile(r'\{([^{}]+)\}')

    max_iterations = 50
    iteration = 0

    while iteration < max_iterations:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text[:match.start()] + random.choice(options) + text[match.end():]
        iteration += 1

    return text


# === Проверка рабочего времени ===
def is_work_time() -> bool:
    """Проверка, находимся ли мы в рабочих часах"""
    now = datetime.now(TIMEZONE)
    return WORK_START_HOUR <= now.hour < WORK_END_HOUR


# === Graceful shutdown ===
shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    logger.info(f"Получен сигнал {signum}, завершаем работу...")
    shutdown_event.set()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# === ХЭНДЛЕР 1: Мониторинг чатов ===
@app.on_message(filters.group & ~filters.bot)
async def chat_listener(client: Client, message: Message):
    try:
        # Получаем текст (включая caption для медиа)
        text = message.text or message.caption or ""
        if not text or not message.from_user:
            return

        # Проверка рабочего времени
        if not is_work_time():
            return

        user_id = message.from_user.id

        # Проверка чёрного списка
        if await db.is_blacklisted(user_id):
            return

        # Проверка, обрабатывали ли уже
        if await db.is_user_processed(user_id):
            return

        # Проверка чата
        active_chats = [c[0] for c in await db.get_chats()]
        current_chat_id = str(message.chat.id)
        current_chat_username = message.chat.username

        if (current_chat_id not in active_chats and
                (not current_chat_username or current_chat_username not in active_chats)):
            return

        # Получаем триггеры и маркеры
        text_lower = text.lower()
        triggers = await db.get_triggers()
        markers = await db.get_markers()

        if not triggers or not markers:
            return

        # Поиск триггеров
        found_trigger = None
        for trigger in triggers:
            if re.search(rf"\b{re.escape(trigger)}", text_lower):
                found_trigger = trigger
                break

        # Поиск маркеров
        found_marker = None
        for marker in markers:
            if re.search(rf"\b{re.escape(marker)}", text_lower):
                found_marker = marker
                break

        # Если найдены оба — это лид
        if found_trigger and found_marker:
            # Медиа = повышенный приоритет
            has_media = bool(message.photo or message.video)
            priority = 2 if has_media else 1

            logger.info(
                f"🔥 Лид в '{message.chat.title}' от {user_id} "
                f"(приоритет: {priority}, медиа: {has_media})"
            )

            await db.log_user_processed(user_id, current_chat_id)
            await db.log_lead(
                user_id=user_id,
                chat_id=current_chat_id,
                chat_title=message.chat.title or "Unknown",
                trigger=found_trigger,
                marker=found_marker,
                message_text=text,
                status="detected"
            )

            # Задержка 5-12 минут
            delay = random.randint(300, 720)
            logger.info(f"⏳ Задержка {delay} сек. для user {user_id}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
                logger.info("Shutdown получен во время ожидания, отменяем отправку")
                return
            except asyncio.TimeoutError:
                pass

            # Rate limit
            if not db.rate_limiter.is_allowed("send_message"):
                logger.warning(f"⚠️ Rate limit, пропускаем user {user_id}")
                await db.log_lead(
                    user_id, current_chat_id, message.chat.title or "",
                    found_trigger, found_marker, text, "rate_limited"
                )
                return

            try:
                raw_template = await db.get_setting("reply_template")
                final_message = parse_spintax(raw_template)

                await client.send_message(chat_id=user_id, text=final_message)
                logger.info(f"✉️ Сообщение доставлено в ЛС user {user_id}")

                await db.log_lead(
                    user_id, current_chat_id, message.chat.title or "",
                    found_trigger, found_marker, text, "sent"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки user {user_id}: {e}")
                await db.log_lead(
                    user_id, current_chat_id, message.chat.title or "",
                    found_trigger, found_marker, text, "error"
                )

    except Exception as e:
        logger.exception(f"Ошибка в chat_listener: {e}")


# === ХЭНДЛЕР 2: Ответы в ЛС ===
@app.on_message(filters.private & ~filters.me & ~filters.bot)
async def private_reply_listener(client: Client, message: Message):
    try:
        if not message.text or not message.from_user:
            return

        user_id = message.from_user.id

        if await db.is_blacklisted(user_id):
            return

        if await db.check_and_set_reply(user_id):
            working_chat_id = await db.get_setting("working_chat_id")

            if working_chat_id:
                try:
                    username = (
                        f"@{message.from_user.username}"
                        if message.from_user.username else "нет юзернейма"
                    )

                    first_name = message.from_user.first_name or ""
                    last_name = message.from_user.last_name or ""

                    # Ссылка на профиль
                    profile_link = (
                        f"https://t.me/{message.from_user.username}"
                        if message.from_user.username
                        else f"tg://user?id={user_id}"
                    )

                    notification_text = (
                        f"🎯 **ПОЛУЧЕН НОВЫЙ ОТКЛИК!**\n\n"
                        f"👤 Клиент: {first_name} {last_name}\n"
                        f"🔗 Профиль: {profile_link}\n"
                        f"🆔 ID: `{user_id}`\n\n"
                        f"💬 **Первый ответ:**\n_{message.text}_\n\n"
                        f"📥 *Зайдите на аккаунт юзербота для продолжения диалога.*"
                    )

                    await client.send_message(
                        chat_id=int(working_chat_id),
                        text=notification_text,
                        parse_mode="Markdown"
                    )

                    # Обновляем статистику
                    async with db.aiosqlite.connect(db.DB_PATH) as conn:
                        await conn.execute("""
                            UPDATE lead_stats SET status='replied'
                            WHERE user_id=? AND status='sent'
                            ORDER BY created_at DESC LIMIT 1
                        """, (user_id,))
                        await conn.commit()

                    logger.info(f"🚀 Уведомление о лиде {user_id} → чат {working_chat_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки в рабочий чат: {e}")

    except Exception as e:
        logger.exception(f"Ошибка в private_reply_listener: {e}")


async def main():
    """Точка входа с graceful shutdown"""
    await db.init_db()
    logger.info("🚀 Запуск юзербота-парсера...")

    try:
        await app.start()
        me = await app.get_me()
        logger.info(f"✅ Авторизован как: {me.first_name} (@{me.username})")

        # Ждём сигнал завершения
        await shutdown_event.wait()
    finally:
        logger.info("Остановка клиента...")
        await app.stop()
        logger.info("👋 Юзербот остановлен")


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt")
