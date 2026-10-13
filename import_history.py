#!/usr/bin/env python3
# import_history.py — одноразовый импорт истории из MAX API в state.db
import sys
import time
from datetime import datetime
import requests

from config import MAX_BOT_TOKEN, MAX_API_BASE, ALLOWED_CHATS
from shared import db, repository


def fetch_batch(chat_id, count=100, to_ms=None):
    """Одна порция сообщений (до 100)."""
    url = f"{MAX_API_BASE}/messages"
    headers = {"Authorization": MAX_BOT_TOKEN}
    params = {"chat_id": chat_id, "count": count}
    if to_ms:
        params["to"] = to_ms

    try:
        r = requests.get(url, params=params, headers=headers, timeout=(5, 30))
        if r.status_code != 200:
            print(f"    ⚠ HTTP {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("messages", [])
    except requests.RequestException as e:
        print(f"    ⚠ {type(e).__name__}: {e}")
        return []


def import_chat(user_id, info):
    """Импорт всей истории одного чата."""
    name = info.get("name", "—")
    chat_id = info.get("chat_id")

    if not chat_id:
        print(f"  ⏭ {name}: chat_id не задан — пропускаю")
        return 0, 0

    print(f"\n📬 {name} (user_id={user_id}, chat_id={chat_id})")

    total_saved = 0
    total_skipped = 0
    to_ms = None
    batch_num = 0

    while True:
        batch_num += 1
        batch = fetch_batch(chat_id, count=100, to_ms=to_ms)

        if not batch:
            break

        # batch приходит от новых к старым
        for msg in batch:
            body = msg.get("body") or {}
            sender = msg.get("sender") or {}

            mid = body.get("mid")
            text = body.get("text", "")
            ts_ms = msg.get("timestamp")
            is_bot = sender.get("is_bot", False)
            sender_id = sender.get("user_id")
            sender_name = sender.get("name") or sender.get("first_name")

            # Определяем direction и author
            if is_bot:
                direction = "out"
                author = "bot"
            else:
                direction = "in"
                author = "user"

            # Проверка дубля
            if repository.is_message_exists(user_id, mid):
                total_skipped += 1
                continue

            # Оригинальная дата из timestamp (Unix ms)
            created_at = None
            if ts_ms:
                created_at = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            else:
                print(f"    ⚠ Нет timestamp для {mid}")

            try:
                repository.save_message(
                    user_id=user_id,
                    mid=mid,
                    text=text,
                    direction=direction,
                    author=author,
                    sender_id=str(sender_id) if sender_id else None,
                    sender_name=sender_name,
                    is_bot=is_bot,
                    chat_id=str(chat_id),
                    timestamp_ms=ts_ms,
                    created_at=created_at,   # ⬅️ ОРИГИНАЛЬНАЯ ДАТА
                )
                total_saved += 1
            except Exception as e:
                print(f"    ⚠ {mid}: {e}")

        # Следующая порция: старше последнего в batch
        oldest_ts = batch[-1].get("timestamp")
        if not oldest_ts or oldest_ts == to_ms:
            break
        to_ms = oldest_ts

        # Rate limit (MAX Bot API)
        time.sleep(0.5)

        if len(batch) < 100:
            break

    print(f"  ✅ сохранено: {total_saved}, пропущено (дубли): {total_skipped}")
    return total_saved, total_skipped


def main():
    print("=" * 70)
    print("  📥 Импорт истории MAX в state.db")
    print("=" * 70)

    db.init_db()

    grand_saved = 0
    grand_skipped = 0

    for user_id, info in ALLOWED_CHATS.items():
        saved, skipped = import_chat(user_id, info)
        grand_saved += saved
        grand_skipped += skipped
        time.sleep(1)  # пауза между чатами

    print()
    print("=" * 70)
    print(f"✅ Готово. Сохранено: {grand_saved}, пропущено: {grand_skipped}")
    print("=" * 70)


if __name__ == "__main__":
    main()