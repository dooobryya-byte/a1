# db.py
import sqlite3
import threading
from datetime import datetime

DB_PATH = "bot_state.db"

# Единый лок для потокобезопасности (у тебя 4+ воркера в разных потоках)
_lock = threading.RLock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы, если их нет. Вызвать один раз при старте."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS MessagesDB (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_datetime TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                id_message TEXT NOT NULL,
                message_text TEXT,
                type_id INTEGER NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS MessagesRel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_datetime TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                id_message_for TEXT NOT NULL,
                id_message_back TEXT NOT NULL
            )
        """)

        # Индексы для быстрых выборок
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_msg_chat_type_dt
            ON MessagesDB (chat_id, type_id, message_datetime)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_msg_chat_idmsg
            ON MessagesDB (chat_id, id_message)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rel_chat_for
            ON MessagesRel (chat_id, id_message_for)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rel_chat_back
            ON MessagesRel (chat_id, id_message_back)
        """)

        conn.commit()
        conn.close()


# ==================== Запись ====================

def insert_message(chat_id, id_message, message_text, type_id):
    """Вставляет сообщение. Возвращает rowid."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO MessagesDB
                (message_datetime, chat_id, id_message, message_text, type_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(chat_id),
            str(id_message),
            message_text,
            int(type_id),
        ))
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid


def insert_rel(chat_id, id_message_for, id_message_back):
    """Создаёт связку. Возвращает rowid."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO MessagesRel
                (message_datetime, chat_id, id_message_for, id_message_back)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(chat_id),
            str(id_message_for),
            str(id_message_back),
        ))
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid


def update_message_text(chat_id, id_message, new_text):
    """Обновляет текст сообщения (для editMessage ⏳ → ответ)."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            UPDATE MessagesDB
            SET message_text = ?
            WHERE chat_id = ? AND id_message = ?
        """, (new_text, str(chat_id), str(id_message)))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        return changed


# ==================== Чтение ====================

def is_message_exists(chat_id, id_message):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM MessagesDB
            WHERE chat_id = ? AND id_message = ?
            LIMIT 1
        """, (str(chat_id), str(id_message)))
        row = cur.fetchone()
        conn.close()
        return row is not None


def get_message_by_id(chat_id, id_message):
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM MessagesDB
            WHERE chat_id = ? AND id_message = ?
            ORDER BY id DESC
            LIMIT 1
        """, (str(chat_id), str(id_message)))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def get_last_by_type(chat_id, type_id, since_datetime=None):
    """Последнее сообщение заданного типа (опционально — с даты)."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        if since_datetime:
            cur.execute("""
                SELECT * FROM MessagesDB
                WHERE chat_id = ? AND type_id = ? AND message_datetime >= ?
                ORDER BY id DESC
                LIMIT 1
            """, (str(chat_id), int(type_id), since_datetime))
        else:
            cur.execute("""
                SELECT * FROM MessagesDB
                WHERE chat_id = ? AND type_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (str(chat_id), int(type_id)))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def get_rel_by_for(chat_id, id_message_for):
    """Связка, где id_message_for = указанный. None, если нет."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM MessagesRel
            WHERE chat_id = ? AND id_message_for = ?
            ORDER BY id DESC
            LIMIT 1
        """, (str(chat_id), str(id_message_for)))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def has_rel_by_for(chat_id, id_message_for):
    """Есть ли вообще связка, где id_message_for = указанный."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM MessagesRel
            WHERE chat_id = ? AND id_message_for = ?
            LIMIT 1
        """, (str(chat_id), str(id_message_for)))
        row = cur.fetchone()
        conn.close()
        return row is not None


def get_unanswered(type_ids):
    """
    Возвращает сообщения указанных типов, у которых НЕТ исходящей связки
    (т.е. на них не ответили / не обработали).
    """
    if not type_ids:
        return []
    placeholders = ",".join("?" * len(type_ids))
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT m.* FROM MessagesDB m
            WHERE m.type_id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM MessagesRel r
                  WHERE r.chat_id = m.chat_id
                    AND r.id_message_for = m.id_message
              )
            ORDER BY m.id ASC
        """, tuple(int(t) for t in type_ids))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_answer_pairs_without_wish():
    """
    НОВЫЙ МЕТОД.
    Возвращает связки 0 → 1, где ответ (TypeID=1) ещё не имеет
    исходящей связки 1 → 2 (т.е. пожелание ещё не отправлено).

    Каждый элемент: dict с ключами
      chat_id, morning_id (id_message_for), answer_id (id_message_back)
    """
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                r.chat_id           AS chat_id,
                r.id_message_for    AS morning_id,
                r.id_message_back   AS answer_id
            FROM MessagesRel r
            JOIN MessagesDB m
              ON m.chat_id = r.chat_id
             AND m.id_message = r.id_message_back
            WHERE m.type_id = 1
              AND NOT EXISTS (
                  SELECT 1 FROM MessagesRel r2
                  WHERE r2.chat_id = r.chat_id
                    AND r2.id_message_for = r.id_message_back
              )
            ORDER BY r.id ASC
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ==================== Очистка ====================

def clear_all():
    """Полная очистка обеих таблиц (для setup_bot.py)."""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM MessagesDB")
        cur.execute("DELETE FROM MessagesRel")
        conn.commit()
        conn.close()


# Инициализация при импорте
init_db()