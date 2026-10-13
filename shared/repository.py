# shared/repository.py
"""
Слой доступа к БД для MAX-бота.

Таблицы:
  chats       — диалоги
  messages    — сообщения (без chat_id, только chat_pk)
  relations   — связки (0→1, 1→2, ...)
  audit_log   — журнал действий
"""

from datetime import datetime
from shared import db


# ==================== Чаты ====================

def get_or_create_chat(user_id: str, chat_id: str = None,
                       name: str = None, city: str = None,
                       gender: str = None) -> int:
    """Возвращает chats.id (внутренний PK)."""
    row = db.fetchone("SELECT id FROM chats WHERE user_id = ?", (str(user_id),))
    if row:
        if chat_id or name or city:
            db.execute("""
                UPDATE chats SET
                    chat_id = COALESCE(?, chat_id),
                    name = COALESCE(?, name),
                    city = COALESCE(?, city),
                    gender = COALESCE(?, gender),
                    updated_at = ?
                WHERE user_id = ?
            """, (chat_id, name, city, gender,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(user_id)))
        return row["id"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("""
        INSERT INTO chats (user_id, chat_id, name, city, gender, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(user_id), chat_id, name or str(user_id), city, gender, now))
    return cur.lastrowid


def get_chat_by_user(user_id: str) -> dict | None:
    return db.fetchone("SELECT * FROM chats WHERE user_id = ?", (str(user_id),))


def list_chats() -> list[dict]:
    """Все чаты с последним сообщением и счётчиком (без удалённых)."""
    return db.fetchall("""
        SELECT
            c.id, c.user_id, c.chat_id, c.name, c.city, c.gender,
            c.updated_at,
            (SELECT COUNT(*) FROM messages m 
             WHERE m.chat_pk = c.id AND m.deleted_at IS NULL) AS msg_count,
            (SELECT text FROM messages m 
             WHERE m.chat_pk = c.id AND m.deleted_at IS NULL
             ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC LIMIT 1) AS last_text,
            (SELECT created_at FROM messages m 
             WHERE m.chat_pk = c.id AND m.deleted_at IS NULL
             ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC LIMIT 1) AS last_at
        FROM chats c
        ORDER BY COALESCE(c.updated_at, c.created_at) DESC
    """)


# ==================== Сообщения ====================

def save_message(user_id: str, mid: str, text: str,
                 direction: str, author: str = None,
                 sender_id: str = None, sender_name: str = None,
                 is_bot: bool = False, chat_id: str = None,
                 type_id: int = None, status: str = "sent",
                 reply_to_mid: str = None,
                 timestamp_ms: int = None,
                 raw_json: str = None,
                 created_at: str = None,
                 attachments: str = None) -> int:
    """
    Сохраняет сообщение. Возвращает messages.id.

    created_at — если не указан, используется текущее локальное время.
    timestamp_ms — ИГНОРИРУЕТСЯ, всегда пересчитывается из created_at.
    attachments — JSON-строка с массивом вложений.
    """
    chat_pk = get_or_create_chat(user_id, chat_id=chat_id)

    # Проверка на дубль по mid
    if mid:
        exists = db.fetchone("SELECT id FROM messages WHERE mid = ?", (mid,))
        if exists:
            return exists["id"]

    # 1. created_at
    if created_at:
        now = created_at
    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 2. timestamp_ms ВСЕГДА из created_at
    try:
        dt = datetime.strptime(now[:19], "%Y-%m-%d %H:%M:%S")
        timestamp_ms = int(dt.timestamp() * 1000)
    except Exception as e:
        print(f"[repository] ⚠ timestamp_ms parse error: {e}")
        timestamp_ms = int(datetime.now().timestamp() * 1000)

    # 3. INSERT
    cur = db.execute("""
        INSERT INTO messages (
            mid, chat_pk, user_id, direction,
            sender_id, sender_name, is_bot, author,
            text, type_id, status, reply_to_mid,
            created_at, timestamp_ms, raw_json, attachments
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        mid, chat_pk, str(user_id), direction,
        sender_id, sender_name, 1 if is_bot else 0, author,
        text, type_id, status, reply_to_mid,
        now, timestamp_ms, raw_json, attachments,
    ))
    return cur.lastrowid


def is_message_exists(chat_id, id_message):
    return db.fetchone("SELECT id FROM messages WHERE mid = ?", (str(id_message),)) is not None


def get_message_by_mid(mid: str) -> dict | None:
    return db.fetchone("SELECT * FROM messages WHERE mid = ?", (mid,))


def get_message_by_id(chat_id, id_message):
    """Совместимость: возвращает сообщение с полями старого API."""
    m = get_message_by_mid(str(id_message))
    if m:
        m["id_message"] = m.get("mid")
        m["message_text"] = m.get("text")
        if m.get("chat_pk"):
            chat = db.fetchone("SELECT user_id FROM chats WHERE id = ?", (m["chat_pk"],))
            if chat:
                m["chat_id"] = str(chat["user_id"])
    return m


def get_last_by_type(chat_id, type_id, since_datetime=None):
    chat_pk = get_or_create_chat(str(chat_id))
    if since_datetime:
        return db.fetchone("""
            SELECT * FROM messages
            WHERE chat_pk = ? AND type_id = ?
              AND created_at >= ? AND deleted_at IS NULL
            ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC LIMIT 1
        """, (chat_pk, type_id, since_datetime))
    return db.fetchone("""
        SELECT * FROM messages
        WHERE chat_pk = ? AND type_id = ? AND deleted_at IS NULL
        ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC LIMIT 1
    """, (chat_pk, type_id))


def get_messages(chat_pk: int, limit: int = 100, before_id: int = None) -> list[dict]:
    """Сообщения чата (в порядке возрастания времени, без удалённых)."""
    if before_id:
        pivot = db.fetchone(
            "SELECT COALESCE(timestamp_ms, 0) AS ts, id FROM messages WHERE id = ?",
            (before_id,)
        )
        if not pivot:
            return []
        rows = db.fetchall("""
            SELECT * FROM messages
            WHERE chat_pk = ?
              AND deleted_at IS NULL
              AND (
                  COALESCE(timestamp_ms, 0) < ?
                  OR (COALESCE(timestamp_ms, 0) = ? AND id < ?)
              )
            ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC
            LIMIT ?
        """, (chat_pk, pivot["ts"], pivot["ts"], pivot["id"], limit))
        return list(reversed(rows))

    rows = db.fetchall("""
        SELECT * FROM messages
        WHERE chat_pk = ? AND deleted_at IS NULL
        ORDER BY COALESCE(timestamp_ms, 0) DESC, id DESC
        LIMIT ?
    """, (chat_pk, limit))
    return list(reversed(rows))


def get_messages_since(user_id: str, since_datetime: str) -> list[dict]:
    """Сообщения чата с указанной даты."""
    chat_pk = get_or_create_chat(str(user_id))
    return db.fetchall("""
        SELECT * FROM messages
        WHERE chat_pk = ? AND created_at >= ? AND deleted_at IS NULL
        ORDER BY COALESCE(timestamp_ms, 0) ASC, id ASC
    """, (chat_pk, since_datetime))


def edit_message(mid: str, new_text: str) -> bool:
    """Локальное редактирование."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("""
        UPDATE messages SET text = ?, edited_at = ?
        WHERE mid = ?
    """, (new_text, now, mid))
    return cur.rowcount > 0


# ⬅️ НОВОЕ: обновление attachments (для enrich url после отправки)
def update_attachments(mid: str, attachments_json: str) -> bool:
    """Обновляет attachments у сообщения по mid."""
    cur = db.execute("""
        UPDATE messages SET attachments = ?
        WHERE mid = ?
    """, (attachments_json, str(mid)))
    return cur.rowcount > 0


def update_message_text(chat_id, id_message, new_text):
    """Совместимость со старым API."""
    return edit_message(str(id_message), new_text)


def delete_message(mid: str) -> bool:
    """Soft delete."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("""
        UPDATE messages SET deleted_at = ?
        WHERE mid = ?
    """, (now, mid))
    return cur.rowcount > 0


# ==================== Связки ====================

def insert_rel(chat_id, id_message_for, id_message_back):
    chat_pk = get_or_create_chat(str(chat_id))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("""
        INSERT INTO relations (chat_pk, id_message_for, id_message_back, created_at)
        VALUES (?, ?, ?, ?)
    """, (chat_pk, str(id_message_for), str(id_message_back), now))
    return cur.lastrowid


def get_rel_by_for(chat_id, id_message_for):
    chat_pk = get_or_create_chat(str(chat_id))
    return db.fetchone("""
        SELECT r.*, c.user_id AS chat_id
        FROM relations r
        JOIN chats c ON c.id = r.chat_pk
        WHERE r.chat_pk = ? AND r.id_message_for = ?
        ORDER BY r.id DESC LIMIT 1
    """, (chat_pk, str(id_message_for)))


def has_rel_by_for(chat_id, id_message_for):
    return get_rel_by_for(chat_id, id_message_for) is not None


def get_unanswered(type_ids):
    if not type_ids:
        return []
    placeholders = ",".join("?" * len(type_ids))
    return db.fetchall(f"""
        SELECT
            m.id, m.mid, m.chat_pk, m.user_id,
            m.direction, m.author, m.text, m.type_id,
            m.sender_id, m.sender_name, m.is_bot,
            m.status, m.created_at, m.timestamp_ms,
            c.user_id AS chat_id
        FROM messages m
        JOIN chats c ON c.id = m.chat_pk
        WHERE m.type_id IN ({placeholders})
          AND m.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM relations r
              WHERE r.chat_pk = m.chat_pk AND r.id_message_for = m.mid
          )
        ORDER BY m.id ASC
    """, tuple(type_ids))


def get_answer_pairs_without_wish():
    return db.fetchall("""
        SELECT
            c.user_id AS chat_id,
            r1.id_message_for AS morning_id,
            r1.id_message_back AS answer_id
        FROM relations r1
        JOIN chats c ON c.id = r1.chat_pk
        JOIN messages m ON m.chat_pk = r1.chat_pk AND m.mid = r1.id_message_back
        WHERE m.type_id = 1
          AND NOT EXISTS (
              SELECT 1 FROM relations r2
              WHERE r2.chat_pk = r1.chat_pk
                AND r2.id_message_for = r1.id_message_back
          )
        ORDER BY r1.id ASC
    """)


# ==================== Совместимость со старым API ====================

def insert_message(chat_id, id_message, message_text, type_id,
                   attachments: str = None):
    """Обёртка над save_message. timestamp_ms НЕ передаём."""
    TYPE_TO_DIR = {
        0: "out", 1: "in", 2: "out", 3: "out",
        4: "out", 5: "in", 7: "out", 8: "out", 9: "in",
    }
    TYPE_TO_AUTHOR = {
        0: "bot", 1: "user", 2: "bot", 3: "bot",
        4: "bot", 5: "user", 7: "bot", 8: "bot", 9: "user",
    }
    return save_message(
        user_id=str(chat_id),
        mid=id_message,
        text=message_text,
        direction=TYPE_TO_DIR.get(type_id, "in"),
        author=TYPE_TO_AUTHOR.get(type_id, "user"),
        is_bot=(TYPE_TO_AUTHOR.get(type_id) == "bot"),
        type_id=type_id,
        attachments=attachments,   # ⬅️ НОВОЕ
    )

# ==================== Аудит ====================

def audit(action: str, chat_pk: int = None, mid: str = None,
          details: str = None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""
        INSERT INTO audit_log (ts, action, chat_pk, mid, details)
        VALUES (?, ?, ?, ?, ?)
    """, (now, action, chat_pk, mid, details))