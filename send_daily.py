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
from utils import is_time_to_send


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"awaiting_reply": {}, "last_sent_date": {}, "answered_ids": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
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
        resp = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    state = load_state()
    sent = 0

    for chat_id, info in ALLOWED_CHATS.items():
        name = info["name"]

        # Уже слали сегодня?
        if state["last_sent_date"].get(chat_id) == today:
            continue

        # Пора ли сейчас?
        if not is_time_to_send(info["morning_hour"], info["morning_minute"], now):
            continue

        # Отправляем
        pool = get_messages_for(chat_id, "DAILY_QUESTION_MESSAGES")
        text = random.choice(pool)
        if send(chat_id, text):
            state["last_sent_date"][chat_id] = today
            state["awaiting_reply"][chat_id] = today
            state["answered_ids"].pop(chat_id, None)
            sent += 1
            print(f"[{now_str()}] ☀️ вопрос отправлен {chat_id} ({name})")

    save_state(state)
    if sent:
        print(f"[{now_str()}] ✅ Отправлено: {sent}")


if __name__ == "__main__":
    main()