#!/usr/bin/env python3
# debug_db.py — просмотр БД бота
import sys
from db import get_recent_messages, get_recent_rels


def print_messages(chat_id=None, limit=30):
    rows = get_recent_messages(chat_id, limit)
    if not rows:
        print("  (нет сообщений)")
        return

    print(f"\n{'ID':<5} {'DateTime':<20} {'ChatID':<12} {'IDMsg':<22} {'Type':<5} {'Text':<40}")
    print("-" * 110)
    for r in rows:
        dt = (r.get("message_datetime") or "")[:19]
        cid = r.get("chat_id", "")
        im = (r.get("id_message") or "")[:20]
        t = r.get("type_id", "?")
        txt = (r.get("message_text") or "")[:38]
        print(f"{r['id']:<5} {dt:<20} {cid:<12} {im:<22} {t:<5} {txt:<40}")


def print_rels(chat_id=None, limit=30):
    rows = get_recent_rels(chat_id, limit)
    if not rows:
        print("  (нет связок)")
        return

    print(f"\n{'ID':<5} {'DateTime':<20} {'ChatID':<12} {'IDFor':<22} {'IDBack':<22}")
    print("-" * 90)
    for r in rows:
        dt = (r.get("message_datetime") or "")[:19]
        cid = r.get("chat_id", "")
        f = (r.get("id_message_for") or "")[:20]
        b = (r.get("id_message_back") or "")[:20]
        print(f"{r['id']:<5} {dt:<20} {cid:<12} {f:<22} {b:<22}")


def main():
    chat_id = sys.argv[1] if len(sys.argv) > 1 else None

    if chat_id:
        print(f"\n=== Сообщения чата {chat_id} ===")
    else:
        print("\n=== Последние сообщения по всем чатам ===")
    print_messages(chat_id)

    if chat_id:
        print(f"\n=== Связки чата {chat_id} ===")
    else:
        print("\n=== Последние связки по всем чатам ===")
    print_rels(chat_id)


if __name__ == "__main__":
    main()