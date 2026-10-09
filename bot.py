# bot.py
import time
import json
import os
import random
import subprocess
import threading
import requests
from datetime import datetime, timedelta

from config import (
    BASE, API_TOKEN, ALLOWED_CHATS, ADMIN_CHAT_ID, ADMIN_NAME,
    POLL_INTERVAL, get_messages_for,
    HERMES_CMD, HERMES_TIMEOUT, HERMES_PREFIXES, HERMES_THINKING_MSG,
    SCHEDULE_SHIFT_MIN, SCHEDULE_WINDOW_MIN,
)

from weather import get_weather   # ⬅️ НОВОЕ: погода напрямую, без Hermes

import db

# ===== TypeID =====
TYPE_MORNING = 0           # утреннее приветствие (требует ответа)
TYPE_ANSWER = 1            # ответ пользователя (требует ответа — пожелание)
TYPE_WISH = 2              # пожелание хорошего дня (ответ не нужен)
TYPE_WARNING = 3           # warning молчуну (ответ не нужен, закрывает 0)
TYPE_ADMIN_ALERT = 4       # сигнал админу (ответ не нужен)
TYPE_HERMES_REQ = 5        # запрос к Hermes (требует ответа)
TYPE_HERMES_WAIT = 7       # ⏳ Ожидание Hermes (требует корректировки)
TYPE_HERMES_ANSWER = 8     # ответ Hermes (ответ не нужен)
TYPE_SERVICE = 9           # служебное / вне цикла

# ===== Глобальные =====
INSTANCE_WID = None
last_heartbeat = time.time()
started_at = time.time()

# Счётчики
total_received = 0
total_sent = 0
total_skipped = 0
total_hermes = 0
total_wishes = 0

# ===== Текст ошибки Hermes =====
HERMES_ERROR_MSG = "⛔ Возникла ошибка при работе 🤖 Hermes"

# seen_ids — быстрый фильтр в памяти
seen_ids = set()


def now_str():
    return datetime.now().strftime("%H:%M:%S")


# ==================== MAX API ====================

def get_instance_wid():
    """Получает wid инстанса (для фильтра своих сообщений)."""
    url = f"{BASE}/getSettings/{API_TOKEN}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("wid")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Не удалось получить wid: {e}")
    return None


def get_messages():
    """
    Входящие сообщения (type=incoming, не от бота).
    Только за последние 10 минут.
    """
    import time as _time
    now_ts = int(_time.time())
    min_ago = now_ts - 600

    url = f"{BASE}/lastIncomingMessages/{API_TOKEN}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                return []
            result = []
            for m in data:
                if m.get("type") != "incoming":
                    continue
                if INSTANCE_WID and m.get("senderId") == INSTANCE_WID:
                    continue
                ts = m.get("timestamp", 0)
                if ts and ts < min_ago:
                    continue
                result.append(m)
            return result
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
        print(f"[{now_str()}] ⚠ Ошибка отправки: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка отправки: {e}")
    return False, None


def edit_message(chat_id, msg_id, new_text):
    """Редактирует сообщение. Возвращает True при успехе."""
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
    """Отправляет длинный текст частями. Возвращает первый idMessage."""
    if not text:
        return None
    first_id = None
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        ok, msg_id = send(chat_id, chunk)
        if first_id is None and ok:
            first_id = msg_id
    return first_id


# ==================== HERMES ====================

def ask_hermes(chat_id, question, timeout=HERMES_TIMEOUT):
    """Вызывает Hermes. Возвращает (answer, error)."""
    session = f"max_{chat_id}"
    cmd = [HERMES_CMD, "-c", session, "-z", question]

    print(f"[{now_str()}] 🤖 Hermes ← [{session}] {question[:80]}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd="/home/a1",
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

    ERROR_MARKERS = (
        "API call failed", "Upstream error", "Service temporarily overloaded",
        "Connection error", "rate limit",
    )
    for marker in ERROR_MARKERS:
        if marker.lower() in answer.lower():
            return None, f"LLM недоступен: {answer[:200]}"

    if not answer:
        return None, "Hermes вернул пустой ответ"

    return answer, None


def run_hermes_shell(command, timeout=HERMES_TIMEOUT):
    """Запускает shell-команду. Возвращает (output, error)."""
    print(f"[{now_str()}] 🐚 Shell ← {command[:80]}")
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd="/home/a1",
        )
    except subprocess.TimeoutExpired:
        return None, f"Превышен тайм-аут {timeout} сек"
    except Exception as e:
        return None, f"Ошибка выполнения: {e}"

    output = (result.stdout or "").strip()
    err = (result.stderr or "").strip()

    if result.returncode != 0 and not output:
        return None, f"Код {result.returncode}: {err[:300]}"

    return output or err, None


def _send_weather(chat_id):
    """
    Отправляет погоду через weather.py (напрямую, без Hermes).
    ⬅️ ИЗМЕНЕНО: раньше был вызов ask_hermes с /hermes Погода...
    """
    info = ALLOWED_CHATS.get(chat_id, {})
    city = (info.get("city") or "").strip()
    if not city:
        print(f"[{now_str()}] ⏭ погода: у чата {chat_id} не задан city")
        return

    print(f"[{now_str()}] 🌤 погода для {chat_id} ({city})")

    try:
        text = get_weather(city)
    except Exception as e:
        print(f"[{now_str()}] ❌ Погода — исключение: {e}")
        return

    if not text:
        print(f"[{now_str()}] ❌ Погода — не удалось собрать для {city}")
        return

    send(chat_id, text)
    print(f"[{now_str()}] ✅ погода отправлена {chat_id} ({city})")


def _send_aphorism(chat_id):
    """Отправляет афоризм дня (не пишет в БД)."""
    try:
        from send_aphorism import get_aphorism
        aphorism = get_aphorism()
        if aphorism:
            send(chat_id, f"📌 Афоризм дня:\n\n{aphorism}")
            print(f"[{now_str()}] 📖 афоризм отправлен {chat_id}")
        else:
            print(f"[{now_str()}] ⏭ афоризм не получен, пропуск")
    except Exception as e:
        print(f"[{now_str()}] ⚠ Ошибка афоризма: {e}")


# ==================== ОБРАБОТКА ВХОДЯЩИХ ====================

def handle_incoming(msg):
    """
    Обрабатывает одно входящее сообщение:
    1. Записывает в MessagesDB с правильным TypeID.
    2. Создаёт связку, если это ответ на предыдущее.
    """
    global total_received, total_skipped

    msg_id = msg.get("idMessage")
    chat_id = msg.get("chatId")
    text = (msg.get("textMessage") or "").strip()
    sender_name = msg.get("senderName", "")

    if not msg_id or not chat_id:
        return

    if msg_id in seen_ids:
        return
    seen_ids.add(msg_id)
    total_received += 1

    if chat_id not in ALLOWED_CHATS:
        print(f"[{now_str()}] ⏭ пропуск {chat_id}: не в списке")
        total_skipped += 1
        return

    if db.is_message_exists(chat_id, msg_id):
        print(f"[{now_str()}] ⏭ {chat_id}: уже в БД, пропуск")
        total_skipped += 1
        return

    print(f"[{now_str()}] ← {sender_name} ({chat_id}): {text[:60]}")

    # === 1. Запрос к Hermes (только админ, с префиксом) ===
    if chat_id == ADMIN_CHAT_ID:
        for prefix in HERMES_PREFIXES:
            if text.startswith(prefix):
                db.insert_message(chat_id, msg_id, text, TYPE_HERMES_REQ)
                _link_if_unanswered(chat_id, msg_id)
                print(f"[{now_str()}] 📝 TypeID=5 (запрос к Hermes)")
                return

    # === 2. Ответ на утреннее приветствие? ===
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    last_morning = db.get_last_by_type(chat_id, TYPE_MORNING, since_datetime=today_start)

    if last_morning and not db.has_rel_by_for(chat_id, last_morning["id_message"]):
        db.insert_message(chat_id, msg_id, text, TYPE_ANSWER)
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=last_morning["id_message"],
            id_message_back=msg_id,
        )
        print(f"[{now_str()}] 📝 TypeID=1 (ответ на утреннее), связка: "
              f"{last_morning['id_message']} → {msg_id}")
        return

    # === 3. Всё остальное — служебное ===
    print(f"[{now_str()}] ⏭ {chat_id}: вне цикла, ответ не нужен")
    db.insert_message(chat_id, msg_id, text, TYPE_SERVICE)
    total_skipped += 1


def _link_if_unanswered(chat_id, msg_id):
    """Создаёт связку 0→5, если есть непрочитанное утреннее."""
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    last_morning = db.get_last_by_type(chat_id, TYPE_MORNING, since_datetime=today_start)
    if last_morning and not db.has_rel_by_for(chat_id, last_morning["id_message"]):
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=last_morning["id_message"],
            id_message_back=msg_id,
        )
        return True
    return False


# ==================== ОБРАБОТЧИКИ ПО TYPEID ====================

def process_type_0_1(chat_id, morning_msg):
    """
    Обрабатывает связку TypeID=0 (утреннее) и TypeID=1 (ответ).
    - Есть связка 0 → 1: пожелание (2) + погода + афоризм.
    - Нет связки 0 → 1 и время >= alert_hour: warning (3) + алерт админу (4).
    """
    morning_id = morning_msg["id_message"]
    info = ALLOWED_CHATS.get(chat_id, {})
    name = info.get("name", chat_id)

    rel = db.get_rel_by_for(chat_id, morning_id)

    if rel and rel.get("id_message_back"):
        answer_msg = db.get_message_by_id(chat_id, rel["id_message_back"])

        if answer_msg and answer_msg["type_id"] == TYPE_ANSWER:
            if db.has_rel_by_for(chat_id, rel["id_message_back"]):
                return

            pool = get_messages_for(chat_id, "ANSWER_MESSAGES")
            if not pool:
                print(f"[{now_str()}] ⚠ {chat_id}: пустой ANSWER_MESSAGES")
                return
            text = random.choice(pool)
            ok, wish_id = send(chat_id, text)
            if not ok or not wish_id:
                print(f"[{now_str()}] ⚠ Не удалось отправить пожелание {chat_id}")
                return

            db.insert_message(chat_id, wish_id, text, TYPE_WISH)
            db.insert_rel(
                chat_id=chat_id,
                id_message_for=rel["id_message_back"],
                id_message_back=wish_id,
            )
            global total_wishes
            total_wishes += 1
            print(f"[{now_str()}] 💬 пожелание отправлено {chat_id}")

            _send_weather(chat_id)
            _send_aphorism(chat_id)
            return

    # Связки 0 → 1 нет → warning
    now = datetime.now()
    ah = info.get("alert_hour", 12)
    am = info.get("alert_minute", 0)
    alert_time = now.replace(hour=ah, minute=am, second=0, microsecond=0)

    if now >= alert_time:
        pool = get_messages_for(chat_id, "WARNING_MESSAGES")
        if not pool:
            print(f"[{now_str()}] ⚠ {chat_id}: пустой WARNING_MESSAGES")
            return
        text = random.choice(pool)
        ok, warn_id = send(chat_id, text)
        if not ok or not warn_id:
            print(f"[{now_str()}] ⚠ Не удалось отправить warning {chat_id}")
            return

        db.insert_message(chat_id, warn_id, text, TYPE_WARNING)
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=morning_id,
            id_message_back=warn_id,
        )
        print(f"[{now_str()}] 🔔 warning отправлен {chat_id}")

        if chat_id != ADMIN_CHAT_ID:
            admin_text = (
                f"⚠️ {ADMIN_NAME}, привет!\n"
                f"{name} сегодня не ответил(а) на утреннее сообщение.\n"
                f"Может, стоит проверить, всё ли в порядке? 💛"
            )
            ok, admin_id = send(ADMIN_CHAT_ID, admin_text)
            if ok and admin_id:
                db.insert_message(ADMIN_CHAT_ID, admin_id, admin_text, TYPE_ADMIN_ALERT)
                print(f"[{now_str()}] 📢 алерт админу отправлен")
        else:
            print(f"[{now_str()}] ⏭ {chat_id} — админ, алерт сам себе не шлём")


def process_type_5(chat_id, req_msg):
    """
    Обрабатывает запрос к Hermes (TypeID=5).
    """
    req_id = req_msg["id_message"]
    text = req_msg["message_text"] or ""

    if db.has_rel_by_for(chat_id, req_id):
        return

    prefix = None
    for p in HERMES_PREFIXES:
        if text.startswith(p):
            prefix = p
            break

    if not prefix:
        return

    question = text[len(prefix):].strip()

    ok, think_id = send(chat_id, HERMES_THINKING_MSG)
    if not ok or not think_id:
        print(f"[{now_str()}] ⚠ Не удалось отправить ⏳ {chat_id}")
        return

    db.insert_message(chat_id, think_id, HERMES_THINKING_MSG, TYPE_HERMES_WAIT)
    db.insert_rel(
        chat_id=chat_id,
        id_message_for=req_id,
        id_message_back=think_id,
    )
    print(f"[{now_str()}] ⏳ ожидание Hermes {chat_id}")

    t = threading.Thread(
        target=_run_hermes_and_edit,
        args=(chat_id, req_id, think_id, question),
        daemon=True,
    )
    t.start()


def _run_hermes_and_edit(chat_id, req_id, think_id, question):
    """Фоновый поток: Hermes → ответ → editMessage ⏳ → ответ."""
    global total_hermes

    if question.startswith("-command "):
        shell_cmd = question[len("-command "):].strip()
        answer, error = run_hermes_shell(shell_cmd)
    else:
        answer, error = ask_hermes(chat_id, question)

    total_hermes += 1

    if error:
        final_text = HERMES_ERROR_MSG
        print(f"[{now_str()}] ❌ Hermes ошибка (в чат отдаём общий текст): {error}")
    else:
        final_text = answer
        print(f"[{now_str()}] ✅ Hermes ответил ({len(answer)} симв.)")

    if think_id:
        first_part = final_text[:4000]
        if edit_message(chat_id, think_id, first_part):
            db.update_message_text(chat_id, think_id, first_part)
            db.insert_message(chat_id, f"{think_id}_ans", final_text, TYPE_HERMES_ANSWER)
            db.insert_rel(
                chat_id=chat_id,
                id_message_for=think_id,
                id_message_back=f"{think_id}_ans",
            )
            print(f"[{now_str()}] ✏️ отредактировано")
            if len(final_text) > 4000:
                send_long(chat_id, final_text[4000:])
        else:
            new_id = send_long(chat_id, final_text)
            if new_id:
                db.insert_message(chat_id, new_id, final_text, TYPE_HERMES_ANSWER)
                db.insert_rel(
                    chat_id=chat_id,
                    id_message_for=think_id,
                    id_message_back=new_id,
                )
            print(f"[{now_str()}] ⚠ fallback: новым сообщением")


# ==================== ВОРКЕРЫ ====================

def daily_worker():
    """Утренняя рассылка. Проверяет каждую минуту для каждого чата."""
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            today_start = f"{today} 00:00:00"

            for chat_id, info in ALLOWED_CHATS.items():
                existing = db.get_last_by_type(chat_id, TYPE_MORNING, since_datetime=today_start)
                if existing:
                    continue

                mh = info.get("morning_hour", 9)
                mm = info.get("morning_minute", 0)
                target = now.replace(hour=mh, minute=mm, second=0, microsecond=0)
                target = target - timedelta(minutes=SCHEDULE_SHIFT_MIN)

                delta_min = (now - target).total_seconds() / 60
                if 0 <= delta_min < SCHEDULE_WINDOW_MIN:
                    pool = get_messages_for(chat_id, "DAILY_QUESTION_MESSAGES")
                    if not pool:
                        continue
                    text = random.choice(pool)
                    ok, msg_id = send(chat_id, text)
                    if ok and msg_id:
                        db.insert_message(chat_id, msg_id, text, TYPE_MORNING)
                        print(f"[{now_str()}] ☀️ утреннее отправлено {chat_id}")
                    else:
                        print(f"[{now_str()}] ⚠ Не удалось отправить утреннее {chat_id}")

            time.sleep(60)
        except Exception as e:
            print(f"[{now_str()}] ⚠ daily_worker error: {e}")
            time.sleep(60)


def alert_worker():
    """Warning-воркер. Каждую минуту проверяет TypeID=0 без связки."""
    while True:
        try:
            unanswered = db.get_unanswered(type_ids=[TYPE_MORNING])
            for msg in unanswered:
                chat_id = msg["chat_id"]
                info = ALLOWED_CHATS.get(chat_id, {})
                ah = info.get("alert_hour", 12)
                am = info.get("alert_minute", 0)
                now = datetime.now()
                alert_time = now.replace(hour=ah, minute=am, second=0, microsecond=0)
                if now >= alert_time:
                    process_type_0_1(chat_id, msg)

            time.sleep(60)
        except Exception as e:
            print(f"[{now_str()}] ⚠ alert_worker error: {e}")
            time.sleep(60)


def wish_worker():
    """
    Отправляет пожелание (TypeID=2) тем, кто ответил на утреннее (0 → 1),
    но ещё не получил пожелание (нет связки 1 → 2).
    """
    while True:
        try:
            pairs = db.get_answer_pairs_without_wish()
            for pair in pairs:
                chat_id = pair["chat_id"]
                morning_id = pair["morning_id"]
                morning_msg = db.get_message_by_id(chat_id, morning_id)
                if not morning_msg:
                    continue
                try:
                    process_type_0_1(chat_id, morning_msg)
                except Exception as e:
                    print(f"[{now_str()}] ⚠ wish_worker process error "
                          f"({chat_id}): {e}")
            time.sleep(30)
        except Exception as e:
            print(f"[{now_str()}] ⚠ wish_worker error: {e}")
            time.sleep(30)


def hermes_worker():
    """Обработка запросов к Hermes (TypeID=5). Каждые 5 секунд."""
    while True:
        try:
            unanswered = db.get_unanswered(type_ids=[TYPE_HERMES_REQ])
            for msg in unanswered:
                process_type_5(msg["chat_id"], msg)
            time.sleep(5)
        except Exception as e:
            print(f"[{now_str()}] ⚠ hermes_worker error: {e}")
            time.sleep(5)


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
              f"| пропущено: {total_skipped} | hermes: {total_hermes} "
              f"| wishes: {total_wishes}")
        last_heartbeat = now


# ==================== HERMES STATUS ====================

def print_hermes_status():
    """Выводит ключевые строки `hermes status` при старте бота."""
    try:
        result = subprocess.run(
            [HERMES_CMD, "status"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd="/home/a1",
        )
        if result.returncode != 0:
            err = (result.stderr or "").strip()[:200]
            print(f"[{now_str()}] ⚠ Hermes status: код {result.returncode}: {err}")
            return

        output = (result.stdout or "").strip()
        if not output:
            print(f"[{now_str()}] 📊 Hermes status: (пусто)")
            return

        KEY_MARKERS = ("Model:", "Provider:", "Providers:", "Gateway:",
                       "Platforms:", "Jobs:")
        print(f"[{now_str()}] 📊 Hermes status:")
        for line in output.splitlines():
            stripped = line.strip()
            if any(stripped.startswith(m) for m in KEY_MARKERS):
                print(f"    {stripped}")
    except subprocess.TimeoutExpired:
        print(f"[{now_str()}] ⚠ Hermes status: таймаут 15 сек")
    except FileNotFoundError:
        print(f"[{now_str()}] ⚠ Hermes status: команда '{HERMES_CMD}' не найдена")
    except Exception as e:
        print(f"[{now_str()}] ⚠ Hermes status: {e}")


# ==================== MAIN ====================

def main():
    global INSTANCE_WID

    INSTANCE_WID = get_instance_wid()
    print(f"[{now_str()}] 📱 Instance WID: {INSTANCE_WID}")
    print(f"[{now_str()}] 🚀 Бот запущен. Чаты: {list(ALLOWED_CHATS.keys())}")
    print(f"[{now_str()}] 🤖 Hermes-команды от чата: {ADMIN_CHAT_ID}")
    print(f"[{now_str()}] Префиксы: {' | '.join(HERMES_PREFIXES)}")

    print_hermes_status()

    # Воркеры
    t_daily = threading.Thread(target=daily_worker, daemon=True)
    t_daily.start()
    print(f"[{now_str()}] ☀️ daily_worker запущен")

    t_alert = threading.Thread(target=alert_worker, daemon=True)
    t_alert.start()
    print(f"[{now_str()}] 🔔 alert_worker запущен")

    t_wish = threading.Thread(target=wish_worker, daemon=True)
    t_wish.start()
    print(f"[{now_str()}] 💬 wish_worker запущен")

    t_hermes = threading.Thread(target=hermes_worker, daemon=True)
    t_hermes.start()
    print(f"[{now_str()}] 🤖 hermes_worker запущен")

    # Основной цикл
    while True:
        for msg in get_messages():
            try:
                handle_incoming(msg)
            except Exception as e:
                print(f"[{now_str()}] ⚠ handle_incoming error: {e}")

        heartbeat()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()