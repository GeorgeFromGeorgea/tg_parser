import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from collections import defaultdict
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "parser_database.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logger = logging.getLogger(__name__)


class RateLimiter:
    """Простой rate limiter на основе скользящего окна"""

    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self.calls[key] = [t for t in self.calls[key] if now - t < self.period]
        if len(self.calls[key]) >= self.max_calls:
            return False
        self.calls[key].append(now)
        return True


# Глобальный rate limiter: до 20 сообщений в минуту
rate_limiter = RateLimiter(
    max_calls=int(os.getenv("RATE_LIMIT_MESSAGES", "20")),
    period=int(os.getenv("RATE_LIMIT_PERIOD", "60"))
)


async def init_db():
    """Инициализация базы данных с миграциями"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # Чаты-доноры
        await db.execute("""
            CREATE TABLE IF NOT EXISTS donor_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT,
                chat_type TEXT DEFAULT 'group',
                created_at INTEGER
            )
        """)

        # Триггеры с категориями
        await db.execute("""
            CREATE TABLE IF NOT EXISTS triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE,
                category TEXT DEFAULT 'general',
                created_at INTEGER
            )
        """)

        # Маркеры
        await db.execute("""
            CREATE TABLE IF NOT EXISTS markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE,
                created_at INTEGER
            )
        """)

        # История сообщений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_history (
                user_id INTEGER PRIMARY KEY,
                sent_at INTEGER,
                has_reply INTEGER DEFAULT 0,
                reply_at INTEGER,
                chat_id TEXT
            )
        """)

        # Настройки
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            )
        """)

        # Чёрный список
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                created_at INTEGER
            )
        """)

        # Статистика лидов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lead_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id TEXT,
                chat_title TEXT,
                trigger_word TEXT,
                marker_word TEXT,
                message_text TEXT,
                status TEXT,
                created_at INTEGER
            )
        """)

        # Маркетинговые кампании (новый функционал)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                template TEXT,
                active INTEGER DEFAULT 1,
                created_at INTEGER
            )
        """)

        # Дефолтные значения
        default_template = (
            "{Привет|Здравствуйте|Добрый день}! Видел ваш {вопрос|запрос} "
            "в чате ЖК. Мы как раз заканчиваем {объект|ремонт} в соседнем корпусе, "
            "могу подсказать по стоимости или прислать смету для примера."
        )
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES ('reply_template', ?, ?)
        """, (default_template, int(time.time())))

        default_markers = [
            "подскажите", "кто делал", "посоветуйте", "ищу",
            "нужен", "мастера", "дайте контакты", "телефон",
            "сколько стоит", "где заказать"
        ]
        for marker in default_markers:
            await db.execute("""
                INSERT OR IGNORE INTO markers (phrase, created_at) VALUES (?, ?)
            """, (marker, int(time.time())))

        await db.commit()
        logger.info("База данных инициализирована")


# === Работа с лидами ===

async def log_lead(user_id: int, chat_id: str, chat_title: str,
                   trigger: str, marker: str, message_text: str, status: str):
    """Логирование лида для статистики"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO lead_stats
            (user_id, chat_id, chat_title, trigger_word, marker_word, message_text, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, str(chat_id), chat_title, trigger, marker,
              message_text[:500] if message_text else "", status, int(time.time())))
        await db.commit()


async def get_stats(days: int = 7):
    """Получить статистику за последние N дней"""
    cutoff = int(time.time()) - (days * 86400)
    async with aiosqlite.connect(DB_PATH) as db:
        # Общее количество лидов
        async with db.execute(
            "SELECT COUNT(*) FROM lead_stats WHERE created_at > ?",
            (cutoff,)
        ) as cur:
            total = (await cur.fetchone())[0]

        # Количество ответов
        async with db.execute(
            "SELECT COUNT(*) FROM lead_stats WHERE status='replied' AND created_at > ?",
            (cutoff,)
        ) as cur:
            replied = (await cur.fetchone())[0]

        # По чатам
        async with db.execute("""
            SELECT chat_title, COUNT(*) as cnt FROM lead_stats
            WHERE created_at > ? GROUP BY chat_title ORDER BY cnt DESC LIMIT 5
        """, (cutoff,)) as cur:
            top_chats = await cur.fetchall()

        # По триггерам
        async with db.execute("""
            SELECT trigger_word, COUNT(*) as cnt FROM lead_stats
            WHERE created_at > ? GROUP BY trigger_word ORDER BY cnt DESC LIMIT 10
        """, (cutoff,)) as cur:
            top_triggers = await cur.fetchall()

    return {
        "total": total,
        "replied": replied,
        "reply_rate": (replied / total * 100) if total else 0,
        "top_chats": top_chats,
        "top_triggers": top_triggers,
    }


# === Чёрный список ===

async def add_to_blacklist(user_id: int, reason: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO blacklist (user_id, reason, created_at)
            VALUES (?, ?, ?)
        """, (user_id, reason, int(time.time())))
        await db.commit()


async def remove_from_blacklist(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
        await db.commit()


async def is_blacklisted(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None


# === История сообщений ===

async def check_and_set_reply(user_id: int) -> bool:
    """Проверяет первый ответ, обновляет статус"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT has_reply FROM message_history WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 0:
                await db.execute("""
                    UPDATE message_history
                    SET has_reply = 1, reply_at = ?
                    WHERE user_id = ?
                """, (int(time.time()), user_id))
                await db.commit()
                return True
    return False


async def is_user_processed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM message_history WHERE user_id = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def log_user_processed(user_id: int, chat_id: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO message_history
            (user_id, sent_at, has_reply, chat_id) VALUES (?, ?, 0, ?)
        """, (user_id, int(time.time()), chat_id))
        await db.commit()


# === Чаты-доноры ===

async def add_chat(chat_id: str, title: str, chat_type: str = "group"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO donor_chats
            (chat_id, title, chat_type, created_at) VALUES (?, ?, ?, ?)
        """, (str(chat_id), title, chat_type, int(time.time())))
        await db.commit()


async def get_chats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id, title, chat_type FROM donor_chats"
        ) as cursor:
            return await cursor.fetchall()


async def remove_chat(chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM donor_chats WHERE chat_id = ?", (str(chat_id),))
        await db.commit()


# === Триггеры и маркеры ===

async def add_trigger(phrase: str, category: str = "general"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO triggers
            (phrase, category, created_at) VALUES (?, ?, ?)
        """, (phrase.lower().strip(), category, int(time.time())))
        await db.commit()


async def get_triggers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT phrase FROM triggers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def remove_trigger(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM triggers WHERE phrase = ?",
            (phrase.lower().strip(),)
        )
        await db.commit()


async def add_marker(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO markers (phrase, created_at) VALUES (?, ?)
        """, (phrase.lower().strip(), int(time.time())))
        await db.commit()


async def get_markers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT phrase FROM markers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def remove_marker(phrase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM markers WHERE phrase = ?",
            (phrase.lower().strip(),)
        )
        await db.commit()


# === Настройки ===

async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""


async def update_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, int(time.time())))
        await db.commit()
