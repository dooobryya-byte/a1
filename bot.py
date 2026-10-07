# bot.py
import time
import json
import os
import random
import subprocess
import requests
from datetime import datetime

from config import (
    BASE, API_TOKEN, ALLOWED_CHATS, ADMIN_CHAT_ID, STATE_FILE,
    POLL_INTERVAL, get_messages_for,
    HERMES_CMD, HERMES_TIMEOUT, HERMES_PREFIXES, HERMES_THINKING_MSG,
)

# ===== Счётчики =====
seen_ids = set()
started_at = time.time()
last_heartbeat = time.time()
total_received = 0
total_sent = 0
total_skipped = 0
total_hermes = 0


def now_str():
    return datetime.now().strftime("%H:%M:%S")


# ==================== STATE ====================

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


# ==================== MAX API ====================

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
    """Отправляет сообщение. Возвращает (ok, idMessage)."""
    global total_sent
    url = f"{BASE}/sendMessage/{API_TOKEN}"
    try:
        resp = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
        if resp.status_code == 200:
            total_sent += 1
            try:
                data = resp.json()
                return True, data.get("idMessage")
            except ValueError:
                return True, None
        print(f"[{now_str()}] ⚠ Ошибка отправки: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка отправки: {e}")
    return False, None


def edit_message(chat_id, msg_id, new_text):
    """Редактирует сообщение по idMessage. Возвращает True при успехе."""
    url = f"{BASE}/editMessage/{API_TOKEN}"
    try:
        resp = requests.post(url, json={
            "chatId": chat_id,
            "idMessage": msg_id,
            "message": new_text,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        print(f"[{now_str()}] ⚠ editMessage: {resp.status_code} {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка редактирования: {e}")
        return False


def send_long(chat_id, text, chunk_size=4000):
    """Отправляет длинный текст, разбивая на части."""
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        send(chat_id, chunk)


# ==================== HERMES ====================

def ask_hermes(chat_id, question, timeout=HERMES_TIMEOUT):
    """
    Вызывает Hermes и возвращает (answer, error).
    """
    session = f"max_{chat_id}"
    cmd = [HERMES_CMD, "--continue", session, "-z", question]

    print(f"[{now_str()}] 🤖 Hermes ← [{session}] {question[:80]}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/home/a1",
        )
    except subprocess.TimeoutExpired:
        return None, f"Превышен тайм-аут {timeout} сек"
    except FileNotFoundError:
        return None, f"Команда '{HERMES_CMD}' не найдена"
    except Exception as e:
        return None, f"Ошибка вызова Hermes: {e}"

    if result.returncode != 0:
        err = (result.stderr or "").strip()[:300]
        return None, f"Hermes код {result.returncode}: {err}"

    answer = (result.stdout or "").strip()

    # Ловим ошибки LLM, которые Hermes может писать в stdout
    ERROR_MARKERS = (
        "API call failed",
        "Upstream error",
        "Service temporarily overloaded",
        "Connection error",
        "rate limit",
    )
    for marker in ERROR_MARKERS:
        if marker.lower() in answer.lower():
            return None, f"LLM недоступен: {answer[:200]}"

    if not answer:
        return None, "Hermes вернул пустой ответ"

    return answer, None


def handle_hermes(chat_id, text):
    """
    Обрабатывает Hermes-команду от админского чата.
    Возвращает True, если сообщение было обработано как Hermes-команда.
    """
    global total_hermes

    # Проверяем префикс (префиксы содержат пробел на конце)
    prefix = None
    for p in HERMES_PREFIXES:
        if text.startswith(p):
            prefix = p
            break

    if prefix is None:
        return False

    question = text[len(prefix):].strip()

    # Пустой вопрос
    if not question:
        send(chat_id, "⚠️ Напиши вопрос после /hermes или ❇")
        total_hermes += 1
        return True

    # 1. Отправляем "⏳ Думаю..."
    ok, think_id = send(chat_id, HERMES_THINKING_MSG)

    # 2. Запрос к Hermes (блокирующий)
    answer, error = ask_hermes(chat_id, question)

    # 3. Готовим финальный текст
    if error:
        final_text = f"⚠️ {error}"
        print(f"[{now_str()}] ❌ Hermes ошибка: {error}")
    else:
        final_text = answer
        print(f"[{now_str()}] ✅ Hermes ответил ({len(answer)} симв.)")

    # 4. Редактируем "⏳" в ответ (первая часть до 4000)
    if ok and think_id:
        first_part = final_text[:4000]
        if edit_message(chat_id, think_id, first_part):
            print(f"[{now_str()}] ✏️ отредактировано ({len(first_part)} симв.)")
            if len(final_text) > 4000:
                remainder = final_text[4000:]
                send_long(chat_id, remainder)
                print(f"[{now_str()}] 📤 остаток ({len(remainder)} симв.)")
        else:
            print(f"[{now_str()}] ⚠ fallback: отправляю новым")
            send_long(chat_id, final_text)
    else:
        print(f"[{now_str()}] ⚠ нет idMessage от '⏳', отправляю новым")
        send_long(chat_id, final_text)

    total_hermes += 1
    return True


# ==================== HEARTBEAT ====================

def heartbeat():
    global last_heartbeat
    now = time.time()
    if now - last_heartbeat >= POLL_INTERVAL:
        uptime = int(now - started_at)
        m, s = divmod(uptime, 60)
        h, m = divmod(m, 60)
        print(f"[{now_str()}] ♥ работает | uptime: {h:02d}:{m:02d}:{s:02d} "
              f"| получено: {total_received} | отправлено: {total_sent} "
              f"| пропущено: {total_skipped} | hermes: {total_hermes}")
        last_heartbeat = now


# ==================== MAIN ====================

print(f"[{now_str()}] 🚀 Бот запущен. Чаты: {list(ALLOWED_CHATS.keys())}")
print(f"[{now_str()}] 🤖 Hermes-команды от чата: {ADMIN_CHAT_ID}")
print(f"[{now_str()}] Префиксы: {' | '.join(HERMES_PREFIXES)}")

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

        # 2. Фильтр собственных служебных сообщений (защита от зацикливания)
        if text in (HERMES_THINKING_MSG,) or text.startswith("⚠️"):
            print(f"[{now_str()}] ⏭ своё служебное сообщение, пропуск")
            total_skipped += 1
            continue

        print(f"[{now_str()}] ← {sender_name} ({chat_id}): {text}")

        # 3. HERMES-команда (только для админа)
        if chat_id == ADMIN_CHAT_ID and handle_hermes(chat_id, text):
            total_skipped += 1
            continue

        # 4. Утренний цикл
        awaiting_today = state["awaiting_reply"].get(chat_id) == today
        already_answered = chat_id in state["answered_ids"]

        if awaiting_today and not already_answered:
            pool = get_messages_for(chat_id, "ANSWER_MESSAGES")
            reply = random.choice(pool)
            ok, _ = send(chat_id, reply)
            if ok:
                print(f"[{now_str()}] 💬 ответ-реакция отправлен {chat_id}")

            state["answered_ids"][chat_id] = msg_id
            state["awaiting_reply"].pop(chat_id, None)
            state_changed = True

        elif awaiting_today and already_answered:
            print(f"[{now_str()}] ⏭ {chat_id}: уже отвечал на утренний вопрос")
            total_skipped += 1

        else:
            print(f"[{now_str()}] ⏭ {chat_id}: вне утреннего цикла, ответ не нужен")
            total_skipped += 1

    if state_changed:
        save_state(state)

    heartbeat()
    time.sleep(POLL_INTERVAL)