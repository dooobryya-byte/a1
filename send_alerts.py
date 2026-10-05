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
    """Собирает текст оповещения для админского чата."""
    if len(silent_list) == 1:
        chat_id, name = silent_list[0]
        return (
            f"⚠️ {ADMIN_NAME}, привет!\n"
            f"{name} сегодня не ответил(а) на утреннее сообщение.\n"
            f"Может, стоит проверить, всё ли в порядке? 💛"
        )
    names = ", ".join(name for _, name in silent_list)
    return (
        f"⚠️ {ADMIN_NAME}, привет!\n"
        f"Сегодня не ответили: {names}.\n"
        f"Может, стоит проверить, всё ли у них в порядке? 💛"
    )


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    alerted = 0
    silent_list = []

    for chat_id, info in ALLOWED_CHATS.items():
        # Админский чат не получает WARNING — он получает сводку
        if chat_id == ADMIN_CHAT_ID:
            continue

        name = info["name"]

        # Ждём ответа только если слали сегодня и флаг не сброшен
        if state["awaiting_reply"].get(chat_id) != today:
            continue

        # 1. Личное напоминание молчуну
        pool = get_messages_for(chat_id, "WARNING_MESSAGES")
        text = random.choice(pool)
        if send(chat_id, text):
            print(f"[{now_str()}] 🔔 предупреждение {chat_id} ({name})")
            alerted += 1
            # Снимаем флаг ТОЛЬКО при успешной отправке
            del state["awaiting_reply"][chat_id]
            silent_list.append((chat_id, name))
        else:
            print(f"[{now_str()}] ⚠ не удалось напомнить {chat_id} ({name}), "
                  f"попробуем в следующий раз")

    # 2. Оповещение в админский чат (одно, со списком)
    if silent_list:
        admin_text = build_admin_notification(silent_list)
        if send(ADMIN_CHAT_ID, admin_text):
            print(f"[{now_str()}] 📢 сводка в админский чат {ADMIN_CHAT_ID} "
                  f"({len(silent_list)} чел.)")
        else:
            print(f"[{now_str()}] ⚠ не удалось отправить сводку в админский чат")

    save_state(state)
    print(f"[{now_str()}] ✅ Напоминаний: {alerted}, "
          f"в сводке: {len(silent_list)}")


if __name__ == "__main__":
    main()