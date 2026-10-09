#!/usr/bin/env python3
# migrate_db.py — пересоздание таблиц MessagesDB и MessagesRel
import sqlite3
import os
import shutil
from datetime import datetime

DB_FILE = "bot_state.db"
BACKUP_SUFFIX = datetime.now().strftime("%Y%m%d_%H%M%S")


def migrate():
    # Бэкап старой БД
    if os.path.exists(DB_FILE):
        backup = f"{DB_FILE}.backup_{BACKUP_SUFFIX}"
        shutil.copy(DB_FILE, backup)
        print(f"Бэкап: {backup}")

    conn = sqlite3.connect(DB_FILE)
    try:
        # Удаляем старые таблицы
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.execute("DROP TABLE IF EXISTS messages_rel")

        # Создаём MessagesDB
        conn.execute("""
            CREATE TABLE messages (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                message_datetime  TEXT NOT NULL,
                chat_id           TEXT NOT NULL,
                id_message        TEXT NOT NULL,
                message_text      TEXT,
                type_id           INTEGER NOT NULL,
                created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX idx_msg_chat_type ON messages(chat_id, type_id)")
        conn.execute("CREATE INDEX idx_msg_id_message ON messages(id_message)")
        conn.execute("CREATE INDEX idx_msg_datetime ON messages(message_datetime)")

        # Создаём MessagesRel
        conn.execute("""
            CREATE TABLE messages_rel (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                message_datetime  TEXT NOT NULL,
                chat_id           TEXT NOT NULL,
                id_message_for    TEXT NOT NULL,
                id_message_back   TEXT NOT NULL,
                created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX idx_rel_chat_for ON messages_rel(chat_id, id_message_for)")
        conn.execute("CREATE INDEX idx_rel_chat_back ON messages_rel(chat_id, id_message_back)")

        conn.commit()
        print("Таблицы пересозданы:")
        print("  - messages (MessagesDB)")
        print("  - messages_rel (MessagesRel)")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()