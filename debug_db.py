#!/usr/bin/env python3
# debug_db.py — просмотр БД max-bot

import sys
import sqlite3
from config import ALLOWED_CHATS

DB_PATH = "bot_state.db"

# Расшифровка TypeID
TYPE_NAMES = {
    0: "☀️ утреннее",
    1: "💬 ответ",
    2: "🎁 пожелание",
    3: "🔔 warning",
    4: "📢 алерт админу",
    5: "🤖 запрос Hermes",
    7: "⏳ ожидание Hermes",
    8: "✅ ответ Hermes",
    9: "🗑️ служебное",
}


def get_name(chat_id: str) -> str:
    """Возвращает имя из ALLOWED_CHATS или '—'."""
    info = ALLOWED_CHATS.get(str(chat_id), {})
    return info.get("name", "—")


def short_mid(mid: str, keep: int = 8) -> str:
    """
    Сокращает mid до вида 'начало...конец'.
    mid.000000001fa5e9aa01a12f5688ea2738 → mid.0000...ea2738
    """
    if not mid:
        return "—"
    if len(mid) <= 2 * keep + 5:
        return mid
    return f"{mid[:keep]}...{mid[-keep:]}"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def print_messages(chat_id=None, limit=30):
    conn = connect()
    cur = conn.cursor()

    if chat_id:
        cur.execute("""
            SELECT id, message_datetime, chat_id, id_message, type_id, message_text
            FROM MessagesDB
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (str(chat_id), limit))
    else:
        cur.execute("""
            SELECT id, message_datetime, chat_id, id_message, type_id, message_text
            FROM MessagesDB
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("  (нет сообщений)")
        return

    print(f"\n{'ID':<5} {'DateTime':<20} {'ChatID':<12} {'Name':<22} {'Type':<20} {'MID':<22} {'Text':<40}")
    print("-" * 145)

    for r in rows:
        dt = (r["message_datetime"] or "")[:19]
        cid = str(r["chat_id"] or "")
        name = get_name(cid)
        t_id = r["type_id"]
        t_name = TYPE_NAMES.get(t_id, f"? ({t_id})")
        mid = short_mid(r["id_message"], 8)
        text = (r["message_text"] or "").replace("\n", " ")[:38]

        print(f"{r['id']:<5} {dt:<20} {cid:<12} {name[:20]:<22} {t_name:<20} {mid:<22} {text:<40}")


def print_rels(chat_id=None, limit=30):
    conn = connect()
    cur = conn.cursor()

    if chat_id:
        cur.execute("""
            SELECT id, message_datetime, chat_id, id_message_for, id_message_back
            FROM MessagesRel
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (str(chat_id), limit))
    else:
        cur.execute("""
            SELECT id, message_datetime, chat_id, id_message_for, id_message_back
            FROM MessagesRel
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("  (нет связок)")
        return

    print(f"\n{'ID':<5} {'DateTime':<20} {'ChatID':<12} {'Name':<22} {'For (morning/answer)':<24} {'Back (answer/wish)':<24}")
    print("-" * 130)

    for r in rows:
        dt = (r["message_datetime"] or "")[:19]
        cid = str(r["chat_id"] or "")
        name = get_name(cid)
        f_id = short_mid(r["id_message_for"], 8)
        b_id = short_mid(r["id_message_back"], 8)

        print(f"{r['id']:<5} {dt:<20} {cid:<12} {name[:20]:<22} {f_id:<24} {b_id:<24}")


def print_chains(limit=20):
    """
    Показывает цепочки 0 → 1 → 2 (утреннее → ответ → пожелание).
    """
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            r1.id AS rel_01_id,
            r1.chat_id,
            r1.message_datetime AS answer_time,
            r1.id_message_for AS morning_mid,
            r1.id_message_back AS answer_mid,
            m1.message_text AS answer_text,
            r2.id_message_back AS wish_mid
        FROM MessagesRel r1
        LEFT JOIN MessagesDB m1
            ON m1.chat_id = r1.chat_id AND m1.id_message = r1.id_message_back
        LEFT JOIN MessagesRel r2
            ON r2.chat_id = r1.chat_id AND r2.id_message_for = r1.id_message_back
        WHERE r1.message_datetime >= date('now', '-1 day')
        ORDER BY r1.id DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("  (нет цепочек)")
        return

    print(f"\n{'Rel01':<7} {'DateTime':<20} {'ChatID':<12} {'Name':<22} {'Morning':<20} {'Answer':<20} {'Wish':<20} {'AnswerText':<30}")
    print("-" * 165)

    for r in rows:
        dt = (r["answer_time"] or "")[:19]
        cid = str(r["chat_id"] or "")
        name = get_name(cid)
        m_mid = short_mid(r["morning_mid"], 8)
        a_mid = short_mid(r["answer_mid"], 8)
        w_mid = short_mid(r["wish_mid"], 8) if r["wish_mid"] else "—"
        ans_txt = (r["answer_text"] or "").replace("\n", " ")[:28]

        print(f"{r['rel_01_id']:<7} {dt:<20} {cid:<12} {name[:20]:<22} {m_mid:<20} {a_mid:<20} {w_mid:<20} {ans_txt:<30}")


def main():
    chat_id = sys.argv[1] if len(sys.argv) > 1 else None

    if chat_id:
        print(f"\n=== Сообщения чата {chat_id} ({get_name(chat_id)}) ===")
        print_messages(chat_id)

        print(f"\n=== Связки чата {chat_id} ({get_name(chat_id)}) ===")
        print_rels(chat_id)
    else:
        print("\n=== Последние сообщения по всем чатам ===")
        print_messages()

        print("\n=== Последние связки по всем чатам ===")
        print_rels()

        print("\n=== Цепочки 0 → 1 → 2 (утреннее → ответ → пожелание) ===")
        print_chains()


if __name__ == "__main__":
    main()