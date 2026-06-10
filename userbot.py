import asyncio
import random
import re
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import database as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

API_ID = 1234567          # Ваши данные
API_HASH = "your_api_hash"  # Ваши данные

app = Client("manager_session", api_id=API_ID, api_hash=API_HASH)

def parse_spintax(text: str) -> str:
    pattern = re.compile(r'\{([^{}]+)\}')
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text.replace(match.group(0), random.choice(options), 1)
    return text

# ХЭНДЛЕР 1: Слушает чаты ЖК (поиск лидов)
@app.on_message(filters.group & ~filters.bot)
async def chat_listener(client: Client, message: Message):
    if not message.text or not message.from_user:
        return

    active_chats = [c[0] for c in await db.get_chats()]
    current_chat_id = str(message.chat.id)
    current_chat_username = message.chat.username

    if current_chat_id not in active_chats and (not current_chat_username or current_chat_username not in active_chats):
        return

    user_id = message.from_user.id
    if await db.is_user_processed(user_id):
        return

    text_lower = message.text.lower()
    triggers = await db.get_triggers()
    markers = await db.get_markers()
    
    if not triggers or not markers:
        return

    trigger_found = any(re.search(rf"\b{re.escape(trigger)}", text_lower) for trigger in triggers)
    marker_found = any(re.search(rf"\b{re.escape(marker)}", text_lower) for marker in markers)

    if trigger_found and marker_found:
        logging.info(f"🔥 Найден валидный лид в чате '{message.chat.title}' от пользователя {user_id}")
        await db.log_user_processed(user_id)
        
        delay = random.randint(300, 720) # Задержка 5-12 минут
        logging.info(f"Запуск таймера задержки на {delay} сек. для пользователя {user_id}")
        await asyncio.sleep(delay)
        
        try:
            raw_template = await db.get_setting("reply_template")
            final_message = parse_spintax(raw_template)
            await client.send_message(chat_id=user_id, text=final_message)
            logging.info(f"✉️ Сообщение успешно доставлено в ЛС пользователю {user_id}")
        except Exception as e:
            logging.error(f"❌ Ошибка отправки сообщения пользователю {user_id}: {e}")


# ОБНОВЛЕНИЕ: ХЭНДЛЕР 2: Слушает ответы в ЛС Юзербота и пересылает в Рабочий Чат
@app.on_message(filters.private & ~filters.me & ~filters.bot)
async def private_reply_listener(client: Client, message: Message):
    if not message.text or not message.from_user:
        return

    user_id = message.from_user.id

    # Проверяем по БД: наш ли это лид и отвечает ли он нам ВПЕРВЫЕ
    if await db.check_and_set_reply(user_id):
        working_chat_id = await db.get_setting("working_chat_id")
        
        if working_chat_id:
            try:
                username = f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма"
                
                # Формируем красивую карточку лида для вашей рабочей группы
                notification_text = (
                    f"🎯 **ПОЛУЧЕН НОВЫЙ ОТКЛИК НА РЕМОНТ!**\n\n"
                    f"👤 Клиент: {message.from_user.first_name} {message.from_user.last_name or ''}\n"
                    f"🔗 Ссылка на профиль: {username}\n"
                    f"🆔 ID пользователя: `{user_id}`\n\n"
                    f"💬 **Первый ответ клиента:**\n_{message.text}_\n\n"
                    f"📥 *Зайдите на аккаунт юзербота, чтобы продолжить диалог и закрыть на замер!*"
                )
                
                # Отправляем сообщение в чат
                await client.send_message(chat_id=int(working_chat_id), text=notification_text, parse_mode="Markdown")
                logging.info(f"🚀 Уведомление о лиде {user_id} отправлено в рабочий чат {working_chat_id}")
            except Exception as e:
                logging.error(f"❌ Не удалось отправить лид в чат: {e}. Убедитесь, что юзербот добавлен в рабочую группу!")

if __name__ == "__main__":
    logging.info("Инициализация и запуск Юзербота-парсера...")
    app.run()