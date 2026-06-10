import aiosqlite
import time

DB_PATH = "parser_database.db"

async def init_db():
    """Инициализация базы данных и создание таблиц"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS donor_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE
            )
        """)
        # ОБНОВЛЕНО: добавлен флаг has_reply (по умолчанию 0 — ответа еще не было)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_history (
                user_id INTEGER PRIMARY KEY,
                sent_at INTEGER,
                has_reply INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) 
            VALUES ('reply_template', '{Привет|Здравствуйте}! Видел ваш question в чате ЖК. Мы как раз заканчиваем объект в соседнем корпусе, могу подсказать по стоимости или прислать смету для примера.')
        """)
        
        default_markers = ["подскажите", "кто делал", "посоветуйте", "ищу", "нужен", "мастера", "дайте контакты", "телефон"]
        for marker in default_markers:
            await db.execute("INSERT OR IGNORE INTO markers (phrase) VALUES (?)", (marker,))
            
        await db.commit()

# --- Новая функция: проверка и фиксация первого ответа ---
async def check_and_set_reply(user_id: int) -> bool:
    """Проверяет, является ли ответ первым. Если да — меняет статус на 1 и возвращает True"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT has_reply FROM message_history WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            # Если пользователь есть в нашей истории и он еще НАМ не отвечал (has_reply == 0)
            if row and row[0] == 0:
                await db.execute("UPDATE message_history SET has_reply = 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                return True
        return False

# --- Остальные стандартные функции без изменений ---
async def add_chat(chat_id: str, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO donor_chats (chat_id, title) VALUES (?, ?)", (str(chat_id), title))
        await db.commit()

async def get_chats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id, title FROM donor_chats") as cursor:
            return await cursor.fetchall()

async def remove_chat(chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM donor_chats WHERE chat_id = ?", (str(chat_id),))
        await db.commit()

async def add_trigger(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO triggers (phrase) VALUES (?)", (phrase.lower().strip(),))
        await db.commit()

async def get_triggers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT phrase FROM triggers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def remove_trigger(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM triggers WHERE phrase = ?", (phrase.lower().strip(),))
        await db.commit()
async def add_marker(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO markers (phrase) VALUES (?)", (phrase.lower().strip(),))
        await db.commit()

async def get_markers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT phrase FROM markers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def remove_marker(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM markers WHERE phrase = ?", (phrase.lower().strip(),))
        await db.commit()

async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

async def update_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def is_user_processed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM message_history WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def log_user_processed(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO message_history (user_id, sent_at, has_reply) VALUES (?, ?, 0)", (user_id, int(time.time())))
        await db.commit()