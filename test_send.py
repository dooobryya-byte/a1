import os
import json
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
        return resp.status_code == 200, resp.text
    except requests.RequestException as e:
        return False, str(e)


def main():
    today = datetime.now().strftime("%Y-%m-%d")

    print("⚠️  Боевой тест: сейчас отправятся реальные сообщения в MAX.\n")
    print("Что отправляем:")

    # Показываем предполагаемые тексты (без сохранения, чтобы не менять state)
    plans = []
    for chat_id, info in ALLOWED_CHATS.items():
        pool = get_messages_for(chat_id, "DAILY_QUESTION_MESSAGES")
        text = random.choice(pool)
        plans.append((chat_id, info, text))
        print(f"  {chat_id} ({info['name']}): {text}")

    confirm = input("\nОтправить? [y/N] ").strip().lower()
    if confirm != "y":
        print("Отменено.")
        return

    print()
    state = load_state()
    sent = 0

    for chat_id, info, text in plans:
        ok, resp = send(chat_id, text)
        status = "✅" if ok else "⚠️"
        print(f"{status} {chat_id} ({info['name']}): {resp[:80]}")

        if ok:
            state["last_sent_date"][chat_id] = today
            state["awaiting_reply"][chat_id] = today
            # Сбрасываем флаг "уже отвечал" — новый вопрос ждёт ответа
            state["answered_ids"].pop(chat_id, None)
            sent += 1

    save_state(state)
    print(f"\n[{now_str()}] 📝 state.json обновлён: "
          f"last_sent_date и awaiting_reply проставлены, "
          f"answered_ids сброшен.")
    print(f"[{now_str()}] ✅ Отправлено: {sent}/{len(plans)}")
    print(f"\nТеперь можно отвечать в MAX и проверять bot.py")


if __name__ == "__main__":
    main()