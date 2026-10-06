# send_alerts.py
import json
import os
import random
import requests
from datetime import datetime

from config import (
    BASE, API_TOKEN, ALLOWED_CHATS, ADMIN_CHAT_ID, ADMIN_NAME,
    STATE_FILE, get_messages_for,
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


def build_admin_notification(silent_list):
    if len(silent_list) == 1:
        _, name = silent_list[0]
        return (
            f"⚠️ {ADMIN_NAME}, привет!\n"
            f"{name} сегодня не ответил(а) на утреннее сообщение.\n"
            f"Может, стоит проверить, всё ли в порядке? 💛"
        )
    names = ", ".join(n for _, n in silent_list)
    return (
        f"⚠️ {ADMIN_NAME}, привет!\n"
        f"Сегодня не ответили: {names}.\n"
        f"Может, стоит проверить, всё ли у них в порядке? 💛"
    )


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    state = load_state()
    alerted = 0
    silent_list = []

    for chat_id, info in ALLOWED_CHATS.items():
        # === ВАРИАНТ A: все получают warning, включая админа. ===
        # TODO: позже переделать, чтобы админ получал только warning или только сводку.
        # См. комментарии ниже.

        # Ждём ответа?
        if state["awaiting_reply"].get(chat_id) != today:
            continue

        # Пора ли сейчас?
        if not is_time_to_send(info["alert_hour"], info["alert_minute"], now):
            continue

        name = info["name"]
        pool = get_messages_for(chat_id, "WARNING_MESSAGES")
        text = random.choice(pool)
        if send(chat_id, text):
            print(f"[{now_str()}] 🔔 предупреждение {chat_id} ({name})")
            alerted += 1
            del state["awaiting_reply"][chat_id]
            silent_list.append((chat_id, name))
        else:
            print(f"[{now_str()}] ⚠ не удалось напомнить {chat_id} ({name})")

    # Сводка админу — отправляется, если кто-то не ответил.
    # Даже если сам админ в списке — сводка всё равно уйдёт ему.
    if silent_list:
        admin_text = build_admin_notification(silent_list)
        if send(ADMIN_CHAT_ID, admin_text):
            print(f"[{now_str()}] 📢 сводка в админский чат ({len(silent_list)} чел.)")

    save_state(state)
    if alerted or silent_list:
        print(f"[{now_str()}] ✅ Напоминаний: {alerted}, в сводке: {len(silent_list)}")


if __name__ == "__main__":
    main()