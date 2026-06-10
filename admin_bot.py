import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command, BaseFilter
from dotenv import load_dotenv

import database as db

load_dotenv()

# === Конфигурация ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
ADMIN_ID = int(os.getenv("ADMIN_ID", "111111111"))
LOG_FILE = os.getenv("ADMIN_LOG_FILE", "admin_bot.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# === Логирование ===
logger = logging.getLogger("admin_bot")
logger.setLevel(getattr(logging, LOG_LEVEL))

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

try:
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)
except Exception as e:
    logger.warning(f"Не удалось создать файловый логгер: {e}")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == ADMIN_ID


# === Graceful shutdown ===
shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    logger.info(f"Получен сигнал {signum}, завершаем...")
    shutdown_event.set()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# === Команды ===
@dp.message(Command("start", "help"), IsAdmin())
async def cmd_start(message: Message):
    help_text = (
        "📊 **Панель управления системой лидогенерации**\n\n"

        "💼 **Главные настройки:**\n"
        "/set\\_work\\_chat ID — Привязать рабочий чат\n\n"

        "🗂 **Чаты-доноры:**\n"
        "/add\\_chat ID — Добавить чат\n"
        "/del\\_chat ID — Удалить чат\n"
        "/chats — Список чатов\n\n"

        "🔑 **Триггеры (что ищут):**\n"
        "/add\\_trigger слово — Добавить\n"
        "/del\\_trigger слово — Удалить\n"
        "/triggers — Список\n\n"

        "📍 **Маркеры (как ищут):**\n"
        "/add\\_marker слово — Добавить\n"
        "/del\\_marker слово — Удалить\n"
        "/markers — Список\n\n"

        "🚫 **Чёрный список:**\n"
        "/blacklist ID — Заблокировать\n"
        "/unblacklist ID — Разблокировать\n\n"

        "📝 **Шаблоны:**\n"
        "/set\\_template текст — Изменить шаблон ответа\n\n"

        "📊 **Статистика:**\n"
        "/stats — Статистика за 7 дней\n"
        "/stats 30 — За 30 дней\n\n"

        "ℹ️ **Прочее:**\n"
        "/health — Статус системы"
    )
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("set_work_chat"), IsAdmin())
async def cmd_set_work_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer(
            "Пример: `/set_work_chat -100123456789`", parse_mode="Markdown"
        )
    chat_id = args[1].strip()
    await db.update_setting("working_chat_id", chat_id)
    await message.answer(
        f"💼 Рабочий чат установлен: `{chat_id}`\n\n"
        f"⚠️ Убедитесь, что юзербот добавлен в этот чат!",
        parse_mode="Markdown"
    )


@dp.message(Command("add_chat"), IsAdmin())
async def cmd_add_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/add_chat -100123456789`", parse_mode="Markdown")
    chat_id = args[1].strip()
    await db.add_chat(chat_id, "Добавлен через пульт")
    await message.answer(f"✅ Чат {chat_id} добавлен.")


@dp.message(Command("chats"), IsAdmin())
async def cmd_list_chats(message: Message):
    chats = await db.get_chats()
    if not chats:
        return await message.answer("Список чатов пуст.")
    res = "\n".join([f"• `{c[0]}` — {c[1]}" for c in chats])
    await message.answer(f"📋 **Активные чаты-доноры:**\n{res}", parse_mode="Markdown")


@dp.message(Command("del_chat"), IsAdmin())
async def cmd_del_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/del_chat ID`")
    chat_id = args[1].strip()
    await db.remove_chat(chat_id)
    await message.answer(f"🗑 Чат {chat_id} удален.")


@dp.message(Command("add_trigger"), IsAdmin())
async def cmd_add_trigger(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/add_trigger плитка`")
    phrase = args[1].strip()
    await db.add_trigger(phrase)
    await message.answer(f"✅ Триггер `{phrase}` добавлен.", parse_mode="Markdown")


@dp.message(Command("triggers"), IsAdmin())
async def cmd_list_triggers(message: Message):
    triggers = await db.get_triggers()
    if not triggers:
        return await message.answer("Список триггеров пуст.")
    res = "\n".join([f"• {t}" for t in triggers])
    await message.answer(f"🔑 **Триггеры:**\n{res}")


@dp.message(Command("del_trigger"), IsAdmin())
async def cmd_del_trigger(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите триггер.")
    phrase = args[1].strip()
    await db.remove_trigger(phrase)
    await message.answer(f"🗑 Триггер `{phrase}` удален.", parse_mode="Markdown")


@dp.message(Command("add_marker"), IsAdmin())
async def cmd_add_marker(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/add_marker посоветуйте`")
    phrase = args[1].strip()
    await db.add_marker(phrase)
    await message.answer(f"✅ Маркер `{phrase}` добавлен.", parse_mode="Markdown")


@dp.message(Command("markers"), IsAdmin())
async def cmd_list_markers(message: Message):
    markers = await db.get_markers()
    if not markers:
        return await message.answer("Список маркеров пуст.")
    res = "\n".join([f"• {m}" for m in markers])
    await message.answer(f"📍 **Маркеры:**\n{res}")


@dp.message(Command("del_marker"), IsAdmin())
async def cmd_del_marker(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите маркер.")
    phrase = args[1].strip()
    await db.remove_marker(phrase)
    await message.answer(f"🗑 Маркер `{phrase}` удален.", parse_mode="Markdown")


@dp.message(Command("set_template"), IsAdmin())
async def cmd_set_template(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите новый текст шаблона.")
    template = args[1].strip()
    await db.update_setting("reply_template", template)
    await message.answer("📝 **Шаблон обновлен.**", parse_mode="Markdown")


# === Новое: Чёрный список ===
@dp.message(Command("blacklist"), IsAdmin())
async def cmd_blacklist(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer(
            "Пример: `/blacklist 123456789 причина`",
            parse_mode="Markdown"
        )
    parts = args[1].split(maxsplit=1)
    try:
        user_id = int(parts[0])
    except ValueError:
        return await message.answer("ID должен быть числом.")
    reason = parts[1] if len(parts) > 1 else "Не указана"
    await db.add_to_blacklist(user_id, reason)
    await message.answer(
        f"🚫 Пользователь `{user_id}` добавлен в ЧС.\nПричина: {reason}",
        parse_mode="Markdown"
    )


@dp.message(Command("unblacklist"), IsAdmin())
async def cmd_unblacklist(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/unblacklist 123456789`")
    try:
        user_id = int(args[1].strip())
    except ValueError:
        return await message.answer("ID должен быть числом.")
    await db.remove_from_blacklist(user_id)
    await message.answer(f"✅ Пользователь `{user_id}` удалён из ЧС.", parse_mode="Markdown")


# === Новое: Статистика ===
@dp.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message):
    args = message.text.split(maxsplit=1)
    days = 7
    if len(args) > 1 and args[1].strip().isdigit():
        days = int(args[1].strip())

    stats = await db.get_stats(days)

    text = (
        f"📊 **Статистика за {days} дней**\n\n"
        f"🔥 Найдено лидов: **{stats['total']}**\n"
        f"✅ Ответили: **{stats['replied']}**\n"
        f"📈 Конверсия: **{stats['reply_rate']:.1f}%**\n\n"
    )

    if stats['top_chats']:
        text += "🏆 **Топ-5 чатов:**\n"
        for title, cnt in stats['top_chats']:
            text += f"• {title}: {cnt}\n"
        text += "\n"

    if stats['top_triggers']:
        text += "🔑 **Топ-10 триггеров:**\n"
        for trig, cnt in stats['top_triggers']:
            text += f"• `{trig}`: {cnt}\n"

    await message.answer(text, parse_mode="Markdown")


# === Health check ===
@dp.message(Command("health"), IsAdmin())
async def cmd_health(message: Message):
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
    now = datetime.now(tz)

    text = (
        f"🟢 **Статус системы**\n\n"
        f"⏰ Время (MSK): `{now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"📅 Рабочие часы: `{os.getenv('WORK_START_HOUR', '8')}:00 - {os.getenv('WORK_END_HOUR', '22')}:00`\n"
        f"🔄 Rate limit: {os.getenv('RATE_LIMIT_MESSAGES', '20')} / {os.getenv('RATE_LIMIT_PERIOD', '60')} сек\n"
        f"🌐 Прокси: {'✅ Включён' if os.getenv('PROXY_ENABLED', 'false').lower() == 'true' else '❌ Выключен'}\n"
    )
    await message.answer(text, parse_mode="Markdown")


async def main():
    await db.init_db()
    logger.info("🚀 Запуск админ-бота...")

    # Отправляем уведомление о старте
    try:
        await bot.send_message(
            ADMIN_ID,
            "🟢 Админ-бот запущен\nИспользуйте /start для справки"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление админу: {e}")

    try:
        # Запускаем polling в фоне, ждём сигнал завершения
        polling_task = asyncio.create_task(dp.start_polling(bot))
        await shutdown_event.wait()
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    finally:
        await bot.session.close()
        logger.info("👋 Админ-бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt")
