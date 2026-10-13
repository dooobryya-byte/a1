# shared/migrate_v2.py
"""
Миграция из старых таблиц MessagesDB/MessagesRel
в новые chats/messages/relations.
"""
import sqlite3
import sys
sys.path.insert(0, "/home/a1/max-bot")

from shared import db
from shared.repository import get_or_create_chat, save_message


def migrate():
    db.init_db()

    # Читаем старое
    old_path = "/home/a1/max-bot/bot_state.db"
    old = sqlite3.connect(old_path)
    old.row_factory = sqlite3.Row

    old_msgs = old.execute("SELECT * FROM MessagesDB ORDER BY id").fetchall()
    old_rels = old.execute("SELECT * FROM MessagesRel ORDER BY id").fetchall()

    print(f"Старых сообщений: {len(old_msgs)}")
    print(f"Старых связок: {len(old_rels)}")

    type_to_author = {
        0: "bot", 1: "user", 2: "bot", 3: "bot",
        4: "bot", 5: "user", 7: "bot", 8: "bot", 9: "user",
    }
    type_to_dir = {
        0: "out", 1: "in", 2: "out", 3: "out",
        4: "out", 5: "in", 7: "out", 8: "out", 9: "in",
    }

    for m in old_msgs:
        user_id = str(m["chat_id"])
        mid = m["id_message"]
        text = m["message_text"] or ""
        type_id = m["type_id"]

        try:
            save_message(
                user_id=user_id,
                mid=mid,
                text=text,
                direction=type_to_dir.get(type_id, "in"),
                author=type_to_author.get(type_id, "user"),
                type_id=type_id,
                is_bot=(type_to_author.get(type_id) == "bot"),
            )
        except Exception as e:
            print(f"  ⚠ {mid}: {e}")

    print(f"✅ Миграция завершена")
    old.close()


if __name__ == "__main__":
    migrate()