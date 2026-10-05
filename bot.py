# bot.py
import time
import json
import os
import random
import requests
from datetime import datetime

from config import (
    BASE, API_TOKEN, ALLOWED_CHATS, STATE_FILE, POLL_INTERVAL,
    get_messages_for,
)

seen_ids = set()
started_at = time.time()
last_heartbeat = time.time()
total_received = 0
total_sent = 0
total_skipped = 0


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


def get_messages():
    url = f"{BASE}/lastIncomingMessages/{API_TOKEN}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return []
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка запроса: {e}")
    return []


def send(chat_id, text):
    global total_sent
    url = f"{BASE}/sendMessage/{API_TOKEN}"
    try:
        resp = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
        if resp.status_code == 200:
            total_sent += 1
            return True
        print(f"[{now_str()}] ⚠ Ошибка отправки: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка отправки: {e}")
    return False


def heartbeat():
    global last_heartbeat
    now = time.time()
    if now - last_heartbeat >= POLL_INTERVAL:
        uptime = int(now - started_at)
        m, s = divmod(uptime, 60)
        h, m = divmod(m, 60)
        print(f"[{now_str()}] ♥ работает | uptime: {h:02d}:{m:02d}:{s:02d} "
              f"| получено: {total_received} | отправлено: {total_sent} "
              f"| пропущено: {total_skipped}")
        last_heartbeat = now


print(f"[{now_str()}] 🚀 Бот запущен. Чаты: {list(ALLOWED_CHATS.keys())}")

while True:
    state = load_state()
    state_changed = False
    today = datetime.now().strftime("%Y-%m-%d")

    for msg in get_messages():
        msg_id = msg.get("idMessage")
        if not msg_id or msg_id in seen_ids:
            continue
        seen_ids.add(msg_id)
        total_received += 1

        chat_id = msg["chatId"]
        text = msg.get("textMessage", "")
        sender_name = msg.get("senderName", "")

        # 1. Фильтр по разрешённым чатам
        if chat_id not in ALLOWED_CHATS:
            print(f"[{now_str()}] ⏭ пропуск {chat_id}: не в списке")
            total_skipped += 1
            continue

        print(f"[{now_str()}] ← {sender_name} ({chat_id}): {text}")

        # 2. Утренний цикл: ждём ли ответа на утренний вопрос?
        awaiting_today = state["awaiting_reply"].get(chat_id) == today
        already_answered = chat_id in state["answered_ids"]

        if awaiting_today and not already_answered:
            # === Отвечаем на утренний вопрос ===
            pool = get_messages_for(chat_id, "ANSWER_MESSAGES")
            reply = random.choice(pool)
            if send(chat_id, reply):
                print(f"[{now_str()}] 💬 ответ-реакция отправлен {chat_id}")

            state["answered_ids"][chat_id] = msg_id
            state["awaiting_reply"].pop(chat_id, None)
            state_changed = True

        elif awaiting_today and already_answered:
            # === Уже отвечал сегодня, не спамим ===
            print(f"[{now_str()}] ⏭ {chat_id}: уже отвечал на утренний вопрос")
            total_skipped += 1

        else:
            # === Вне утреннего цикла ===
            print(f"[{now_str()}] ⏭ {chat_id}: вне утреннего цикла, ответ не нужен")
            total_skipped += 1

    if state_changed:
        save_state(state)

    heartbeat()
    time.sleep(POLL_INTERVAL)