# send_daily.py
import json
import os
import random
import requests
from datetime import datetime

from config import (
    BASE, API_TOKEN, ALLOWED_CHATS, STATE_FILE,
    get_messages_for,
)


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"awaiting_reply": {}, "last_sent_date": {}, "answered_ids": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    # миграция: если state.json из старой версии
    state.setdefault("awaiting_reply", {})
    state.setdefault("last_sent_date", {})
    state.setdefault("answered_ids", {})
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send(chat_id, text):
    url = f"{BASE}/sendMessage/{API_TOKEN}"
    try:
        resp = requests.post(
            url,
            json={"chatId": chat_id, "message": text},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        print(f"[{now_str()}] ⚠ Ошибка отправки в {chat_id}: "
              f"{resp.status_code} {resp.text}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка отправки в {chat_id}: {e}")
    return False


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    sent = 0
    skipped = 0

    print(f"[{now_str()}] ☀️ Запуск утренней рассылки")

    for chat_id, info in ALLOWED_CHATS.items():
        name = info["name"]

        # Уже слали сегодня?
        if state["last_sent_date"].get(chat_id) == today:
            print(f"[{now_str()}] ⏭ {chat_id} ({name}) — уже слали сегодня")
            skipped += 1
            continue

        # Выбираем случайный вопрос с учётом рода
        pool = get_messages_for(chat_id, "DAILY_QUESTION_MESSAGES")
        text = random.choice(pool)

        if send(chat_id, text):
            # Помечаем факт отправки
            state["last_sent_date"][chat_id] = today
            # Ждём ответа от этого чата
            state["awaiting_reply"][chat_id] = today
            # Сбрасываем флаг "уже отвечал" — новый вопрос ждёт ответа
            state["answered_ids"].pop(chat_id, None)
            sent += 1
            print(f"[{now_str()}] ☀️ вопрос отправлен {chat_id} ({name})")

    save_state(state)
    print(f"[{now_str()}] ✅ Рассылка завершена. "
          f"Отправлено: {sent}, пропущено: {skipped}")


if __name__ == "__main__":
    main()