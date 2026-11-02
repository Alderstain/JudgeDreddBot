import aiosqlite
import os
import sqlite3
from typing import List, Optional, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "court.db")

CATEGORIES = {
    "toxicity": {
        "title": "Токсичность",
        "description": "Оскорбления, агрессия, травля, провокации",
        "emoji": "☣️"
    },
    "disorder": {
        "title": "Дебош",
        "description": "Спам, флуд, помехи в чате или голосовых каналах",
        "emoji": "📢"
    },
    "sabotage": {
        "title": "Вредительство",
        "description": "Спойлеры, слив информации, порча игр или мероприятий",
        "emoji": "💣"
    }
}


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                report_threshold INTEGER DEFAULT 3,
                court_category_id INTEGER DEFAULT NULL,
                statement_timeout INTEGER DEFAULT 180,
                auto_timeout_minutes INTEGER DEFAULT 60,
                jury_voting_enabled INTEGER DEFAULT 1,
                jury_voting_duration INTEGER DEFAULT 60
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                accuser_id INTEGER NOT NULL,
                accused_id INTEGER NOT NULL,
                category TEXT DEFAULT 'toxicity',
                reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                case_id INTEGER DEFAULT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_number INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER,
                accused_id INTEGER NOT NULL,
                category TEXT DEFAULT 'toxicity',
                status TEXT DEFAULT 'in_progress',
                verdict TEXT DEFAULT NULL,
                verdict_text TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Мягкая миграция для category
        try:
            await db.execute("ALTER TABLE complaints ADD COLUMN category TEXT DEFAULT 'toxicity'")
        except sqlite3.OperationalError:
            pass

        try:
            await db.execute("ALTER TABLE cases ADD COLUMN category TEXT DEFAULT 'toxicity'")
        except sqlite3.OperationalError:
            pass

        # Мягкая миграция для jury voting
        try:
            await db.execute("ALTER TABLE guild_settings ADD COLUMN jury_voting_enabled INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass

        try:
            await db.execute("ALTER TABLE guild_settings ADD COLUMN jury_voting_duration INTEGER DEFAULT 60")
        except sqlite3.OperationalError:
            pass

        await db.commit()


async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            
            await db.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
            )
            await db.commit()
            return {
                "guild_id": guild_id,
                "report_threshold": 3,
                "court_category_id": None,
                "statement_timeout": 180,
                "auto_timeout_minutes": 60,
                "jury_voting_enabled": 1,
                "jury_voting_duration": 60
            }


async def update_guild_settings(guild_id: int, **kwargs):
    if not kwargs:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [guild_id]
        query = f"UPDATE guild_settings SET {set_clause} WHERE guild_id = ?"
        await db.execute(query, values)
        await db.commit()


async def add_complaint(guild_id: int, accuser_id: int, accused_id: int, reason: str, category: str = "toxicity") -> bool:
    """Добавляет жалобу. Возвращает False, если обвинитель уже подавал активную жалобу на этого обвиняемого по данной категории."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id FROM complaints 
               WHERE guild_id = ? AND accuser_id = ? AND accused_id = ? AND category = ? AND status = 'pending'""",
            (guild_id, accuser_id, accused_id, category)
        ) as cursor:
            if await cursor.fetchone():
                return False

        await db.execute(
            """INSERT INTO complaints (guild_id, accuser_id, accused_id, category, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, accuser_id, accused_id, category, reason)
        )
        await db.commit()
        return True


async def get_pending_complaints(guild_id: int, accused_id: int, category: Optional[str] = None) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if category:
            query = """SELECT * FROM complaints 
                       WHERE guild_id = ? AND accused_id = ? AND category = ? AND status = 'pending'
                       ORDER BY created_at ASC"""
            params = (guild_id, accused_id, category)
        else:
            query = """SELECT * FROM complaints 
                       WHERE guild_id = ? AND accused_id = ? AND status = 'pending'
                       ORDER BY created_at ASC"""
            params = (guild_id, accused_id)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def create_case(guild_id: int, accused_id: int, complaint_ids: List[int], category: str = "toxicity") -> int:
    """Создает новое дело по конкретной категории, связывает жалобы и возвращает номер дела."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(MAX(case_number), 0) + 1 FROM cases WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            case_number = (await cursor.fetchone())[0]

        cursor = await db.execute(
            """INSERT INTO cases (case_number, guild_id, accused_id, category, status)
               VALUES (?, ?, ?, ?, 'in_progress')""",
            (case_number, guild_id, accused_id, category)
        )
        case_id = cursor.lastrowid

        placeholders = ",".join("?" for _ in complaint_ids)
        await db.execute(
            f"""UPDATE complaints 
                SET status = 'in_trial', case_id = ?
                WHERE id IN ({placeholders})""",
            [case_id] + complaint_ids
        )
        await db.commit()
        return case_number


async def update_case_channel(guild_id: int, case_number: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE cases SET channel_id = ? WHERE guild_id = ? AND case_number = ?",
            (channel_id, guild_id, case_number)
        )
        await db.commit()


async def close_case(guild_id: int, case_number: int, verdict: str, verdict_text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE cases 
               SET status = 'completed', verdict = ?, verdict_text = ?
               WHERE guild_id = ? AND case_number = ?""",
            (verdict, verdict_text, guild_id, case_number)
        )
        await db.execute(
            """UPDATE complaints
               SET status = 'resolved'
               WHERE guild_id = ? AND case_id = (SELECT id FROM cases WHERE guild_id = ? AND case_number = ?)""",
            (guild_id, guild_id, case_number)
        )
        await db.commit()
