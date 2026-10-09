# db.py
import sqlite3
import os
from datetime import datetime

DB_FILE = "bot_state.db"


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ==================== MESSAGESDB ====================

def insert_message(chat_id, id_message, text, type_id):
    """
    Записывает сообщение в MessagesDB.
    Возвращает ID записи или None.
    """
    conn = get_conn()
    try:
        cur = conn.execute("""
            INSERT INTO messages
                (message_datetime, chat_id, id_message, message_text, type_id)
            VALUES (?, ?, ?, ?, ?)
        """, (now_iso(), chat_id, id_message, text, type_id))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_message_by_id(chat_id, id_message):
    """Находит сообщение по chat_id + id_message."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM messages
            WHERE chat_id = ? AND id_message = ?
            ORDER BY id DESC
            LIMIT 1
        """, (chat_id, id_message)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_message_by_rowid(rowid):
    """Находит сообщение по внутреннему ID."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (rowid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_message_text(chat_id, id_message, new_text):
    """Обновляет текст сообщения (для корректировки ⏳ → ответ Hermes)."""
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE messages
            SET message_text = ?
            WHERE chat_id = ? AND id_message = ?
        """, (new_text, chat_id, id_message))
        conn.commit()
    finally:
        conn.close()


def get_last_by_type(chat_id, type_id, since_datetime=None):
    """
    Возвращает последнее сообщение с указанным TypeID для чата.
    since_datetime (опционально): только после указанного времени.
    """
    conn = get_conn()
    try:
        if since_datetime:
            row = conn.execute("""
                SELECT * FROM messages
                WHERE chat_id = ? AND type_id = ?
                  AND message_datetime >= ?
                ORDER BY id DESC
                LIMIT 1
            """, (chat_id, type_id, since_datetime)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM messages
                WHERE chat_id = ? AND type_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (chat_id, type_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_by_type_since(chat_id, type_id, since_datetime):
    """Все сообщения указанного типа после времени."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM messages
            WHERE chat_id = ? AND type_id = ?
              AND message_datetime >= ?
            ORDER BY id ASC
        """, (chat_id, type_id, since_datetime)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def is_message_exists(chat_id, id_message):
    """Есть ли сообщение с таким idMessage в БД."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT 1 FROM messages
            WHERE chat_id = ? AND id_message = ?
            LIMIT 1
        """, (chat_id, id_message)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_unanswered(chat_id=None, type_ids=None):
    """
    Возвращает сообщения, которые требуют ответа, но не имеют связки.
    type_ids — список TypeID, которые надо проверить (например, [0, 1, 5, 7]).
    """
    if type_ids is None:
        type_ids = [0, 1, 5, 7]

    placeholders = ",".join("?" * len(type_ids))
    conn = get_conn()
    try:
        if chat_id:
            rows = conn.execute(f"""
                SELECT m.* FROM messages m
                WHERE m.type_id IN ({placeholders})
                  AND m.chat_id = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM messages_rel r
                    WHERE r.chat_id = m.chat_id
                      AND r.id_message_for = m.id_message
                  )
                ORDER BY m.id ASC
            """, (*type_ids, chat_id)).fetchall()
        else:
            rows = conn.execute(f"""
                SELECT m.* FROM messages m
                WHERE m.type_id IN ({placeholders})
                  AND NOT EXISTS (
                    SELECT 1 FROM messages_rel r
                    WHERE r.chat_id = m.chat_id
                      AND r.id_message_for = m.id_message
                  )
                ORDER BY m.id ASC
            """, tuple(type_ids)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== MESSAGESREL ====================

def insert_rel(chat_id, id_message_for, id_message_back):
    """Создаёт связку между сообщениями."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO messages_rel
                (message_datetime, chat_id, id_message_for, id_message_back)
            VALUES (?, ?, ?, ?)
        """, (now_iso(), chat_id, id_message_for, id_message_back))
        conn.commit()
    finally:
        conn.close()


def has_rel_by_for(chat_id, id_message_for):
    """Есть ли связка, где IDMessageFor = указанный."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT 1 FROM messages_rel
            WHERE chat_id = ? AND id_message_for = ?
            LIMIT 1
        """, (chat_id, id_message_for)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_rel_by_for(chat_id, id_message_for):
    """Возвращает связку по IDMessageFor."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM messages_rel
            WHERE chat_id = ? AND id_message_for = ?
            ORDER BY id DESC
            LIMIT 1
        """, (chat_id, id_message_for)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ==================== ОТЛАДКА ====================

def get_recent_messages(chat_id=None, limit=20):
    """Последние сообщения (для debug_db.py)."""
    conn = get_conn()
    try:
        if chat_id:
            rows = conn.execute("""
                SELECT * FROM messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (chat_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM messages
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_rels(chat_id=None, limit=20):
    """Последние связки (для debug_db.py)."""
    conn = get_conn()
    try:
        if chat_id:
            rows = conn.execute("""
                SELECT * FROM messages_rel
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (chat_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM messages_rel
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()