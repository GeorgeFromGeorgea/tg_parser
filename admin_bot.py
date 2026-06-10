import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command, BaseFilter
import database as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BOT_TOKEN = "your_bot_token_here"
ADMIN_ID = 111111111  # Ваш личный ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == ADMIN_ID

@dp.message(Command("start"), IsAdmin())
async def cmd_start(message: Message):
    help_text = (
        "📊 **Панель управления системой лидогенерации**\n\n"
        "💼 **Главная настройка уведомлений:**\n"
        "/set_work_chat ID — Привязать закрытый рабочий чат для лидов\n\n"
        "🗂 **Чаты-доноры:**\n"
        "/add_chat — Добавить чат ЖК\n"
        "/del_chat — Удалить чат ЖК\n"
        "/chats — Список отслеживаемых чатов\n\n"
        "🔑 **Слова-триггеры (Что ищут):**\n"
        "/add_trigger слово — Добавить предмет поиска\n"
        "/del_trigger — Удалить предмет поиска\n"
        "/triggers — Список всех триггеров\n\n"
        "📍 **Маркеры контекста (Как ищут):**\n"
        "/add_marker слово — Добавить маркер\n"
        "/del_marker слово — Удалить маркер\n"
        "/markers — Список всех маркеров\n\n"
        "📝 **Оффер (Шаблон ответа):**\n"
        "/set_template — Изменить текст ответа в ЛС"
    )
    await message.answer(help_text, parse_mode="Markdown")

# --- НОВАЯ КОМАНДА: Установка рабочего чата ---
@dp.message(Command("set_work_chat"), IsAdmin())
async def cmd_set_work_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример использования: `/set_work_chat -100123456789`", parse_mode="Markdown")
    chat_id = args[1].strip()
    await db.update_setting("working_chat_id", chat_id)
    await message.answer(
        f"💼 Рабочий чат успешно установлен: `{chat_id}`\n\n"
        f"⚠️ *Важно:* Убедитесь, что ваш аккаунт-юзербот добавлен в этот чат как участник, иначе он не сможет присылать туда уведомления!", 
        parse_mode="Markdown"
    )

# --- Остальные команды управления без изменений ---
@dp.message(Command("add_chat"), IsAdmin())
async def cmd_add_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/add_chat -100123456789`", parse_mode="Markdown")
    chat_id = args[1].strip()
    await db.add_chat(chat_id, "Добавлен через пульт")
    await message.answer(f"✅ Чат {chat_id} внесен в список.")

@dp.message(Command("chats"), IsAdmin())
async def cmd_list_chats(message: Message):
    chats = await db.get_chats()
    if not chats:
        return await message.answer("Список чатов пуст.")
    res = "\n".join([f"• `{c[0]}`" for c in chats])
    await message.answer(f"📋 **Список активных чатов-доноров:**\n{res}", parse_mode="Markdown")

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
        return await message.answer("Пример: `/add_trigger плитк`")
    phrase = args[1].strip()
    await db.add_trigger(phrase)
    await message.answer(f"✅ Слово-триггер {phrase} добавлено.")

@dp.message(Command("triggers"), IsAdmin())
async def cmd_list_triggers(message: Message):
    triggers = await db.get_triggers()
    if not triggers:
        return await message.answer("Список триггеров пуст.")
    res = "\n".join([f"• {t}" for t in triggers])
    await message.answer(f"🔑 **Действующие слова-триггеры:**\n{res}")

@dp.message(Command("del_trigger"), IsAdmin())
async def cmd_del_trigger(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите триггер.")
    phrase = args[1].strip()
    await db.remove_trigger(phrase)
    await message.answer(f"🗑 Триггер {phrase} удален.")

@dp.message(Command("add_marker"), IsAdmin())
async def cmd_add_marker(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Пример: `/add_marker посовет`")
    phrase = args[1].strip()
    await db.add_marker(phrase)
    await message.answer(f"✅ Маркер контекста {phrase} внедрен.")

@dp.message(Command("markers"), IsAdmin())
async def cmd_list_markers(message: Message):
    markers = await db.get_markers()
    if not markers:
        return await message.answer("Список маркеров пуст.")
    res = "\n".join([f"• {m}" for m in markers])
    await message.answer(f"📍 **Действующие маркеры намерения:**\n{res}")

@dp.message(Command("del_marker"), IsAdmin())
async def cmd_del_marker(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите маркер.")
    phrase = args[1].strip()
    await db.remove_marker(phrase)
    await message.answer(f"🗑 Маркер {phrase} удален.")

@dp.message(Command("set_template"), IsAdmin())
async def cmd_set_template(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Укажите новый текст шаблона.")
    template = args[1].strip()
    await db.update_setting("reply_template", template)
    await message.answer("📝 **Шаблон автоответа обновлен.**")

async def main():
    await db.init_db()
    logging.info("Запуск сервера админ-панели...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())