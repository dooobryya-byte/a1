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
    MAX_BOT_TOKEN, MAX_API_BASE, MAX_API_TIMEOUT,
    MAX_POLL_TIMEOUT, MAX_POLL_LIMIT,
    ALLOWED_CHATS, ADMIN_CHAT_ID, ADMIN_NAME,
    POLL_INTERVAL, get_messages_for,
    HERMES_CMD, HERMES_TIMEOUT, HERMES_PREFIXES, HERMES_THINKING_MSG,
    SCHEDULE_SHIFT_MIN, SCHEDULE_WINDOW_MIN,
)

from weather import get_weather
from shared import repository as db

# ===== TypeID =====
TYPE_MORNING = 0
TYPE_ANSWER = 1
TYPE_WISH = 2
TYPE_WARNING = 3
TYPE_ADMIN_ALERT = 4
TYPE_HERMES_REQ = 5
TYPE_HERMES_WAIT = 7
TYPE_HERMES_ANSWER = 8
TYPE_SERVICE = 9

# ===== Глобальные =====
POLL_MARKER = None
last_heartbeat = time.time()
started_at = time.time()

total_received = 0
total_sent = 0
total_skipped = 0
total_hermes = 0
total_wishes = 0

HERMES_ERROR_MSG = "⛔ Возникла ошибка при работе 🤖 Hermes"
seen_ids = set()


def now_str():
    return datetime.now().strftime("%H:%M:%S")


# ==================== MAX API ====================

def get_messages():
    """Long polling MAX. Возвращает входящие в формате handle_incoming."""
    global POLL_MARKER

    url = f"{MAX_API_BASE}/updates"
    headers = {"Authorization": MAX_BOT_TOKEN}
    params = {
        "timeout": MAX_POLL_TIMEOUT,
        "limit": MAX_POLL_LIMIT,
    }
    if POLL_MARKER is not None:
        params["marker"] = POLL_MARKER

    try:
        resp = requests.get(
            url, params=params, headers=headers,
            timeout=(MAX_API_TIMEOUT[0], MAX_POLL_TIMEOUT + 10),
        )
        if resp.status_code != 200:
            print(f"[{now_str()}] ⚠ poll: HTTP {resp.status_code} {resp.text[:200]}")
            return []

        data = resp.json() or {}
        POLL_MARKER = data.get("marker", POLL_MARKER)

        updates = data.get("updates", [])
        result = []
        for upd in updates:
            if upd.get("update_type") != "message_created":
                continue
            msg = upd.get("message") or {}
            sender = msg.get("sender") or {}
            recipient = msg.get("recipient") or {}
            body = msg.get("body") or {}

            # Пропускаем свои же
            if str(sender.get("user_id")) == str(recipient.get("user_id")):
                continue

            attachments_raw = body.get("attachments") or []
            attachments_clean = []
            for a in attachments_raw:
                c = {"type": a.get("type")}
                payload = a.get("payload") or {}
                if payload.get("url"):       c["url"] = payload["url"]
                if payload.get("token"):     c["token"] = payload["token"]
                if payload.get("photo_id"):  c["photo_id"] = payload["photo_id"]
                if a.get("filename"):        c["filename"] = a["filename"]
                attachments_clean.append(c)

            adapted = {
                "idMessage": body.get("mid"),
                "chatId": str(sender.get("user_id")),
                "chat_id": str(recipient.get("chat_id")),
                "textMessage": body.get("text", ""),
                "attachments": attachments_clean,   # ⬅️ НОВОЕ
                "senderName": sender.get("name", ""),
                "senderId": str(sender.get("user_id")),
                "isBot": sender.get("is_bot", False),
                "timestamp_ms": msg.get("timestamp"),
                "type": "incoming",
            }
            if adapted["idMessage"] and adapted["chatId"]:
                result.append(adapted)

        return result

    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ poll MAX: {e}")
        return []


def send(chat_id, text):
    """Отправляет сообщение в MAX. Возвращает (ok, mid)."""
    global total_sent

    url = f"{MAX_API_BASE}/messages"
    params = {"user_id": chat_id}
    headers = {
        "Authorization": MAX_BOT_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"text": text}

    try:
        resp = requests.post(
            url, params=params, json=payload,
            headers=headers, timeout=MAX_API_TIMEOUT,
        )
        if resp.status_code == 200:
            total_sent += 1
            try:
                data = resp.json()
                mid = (
                    ((data.get("message") or {}).get("body") or {}).get("mid")
                    or (data.get("body") or {}).get("mid")
                    or data.get("mid")
                )
                return True, mid
            except ValueError:
                return True, None
        print(f"[{now_str()}] ⚠ Ошибка отправки MAX: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка отправки MAX: {e}")
    return False, None


def edit_message(chat_id, msg_id, new_text):
    """Редактирует сообщение в MAX."""
    url = f"{MAX_API_BASE}/messages"
    headers = {
        "Authorization": MAX_BOT_TOKEN,
        "Content-Type": "application/json",
    }
    params = {"message_id": msg_id}
    payload = {"text": new_text}

    try:
        resp = requests.put(
            url, params=params, json=payload,
            headers=headers, timeout=MAX_API_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        print(f"[{now_str()}] ⚠ editMessage MAX: {resp.status_code} {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ Ошибка редактирования MAX: {e}")
        return False


def send_long(chat_id, text, chunk_size=4000):
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
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        err_text = stderr or stdout or "(no output)"
        return None, f"Hermes код {result.returncode}: {err_text[:300]}"

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

    ok, mid = send(chat_id, text)
    if ok and mid:
        db.insert_message(chat_id, mid, text, TYPE_WISH)
        print(f"[{now_str()}] ✅ погода отправлена {chat_id} ({city})")
    else:
        print(f"[{now_str()}] ⚠ погода не отправлена {chat_id} ({city})")


def _send_aphorism(chat_id):
    try:
        from send_aphorism import get_aphorism
        aphorism = get_aphorism()
        if aphorism:
            text = f"📌 Афоризм дня:\n\n{aphorism}"
            ok, mid = send(chat_id, text)
            if ok and mid:
                db.insert_message(chat_id, mid, text, TYPE_WISH)
                print(f"[{now_str()}] 📖 афоризм отправлен {chat_id}")
            else:
                print(f"[{now_str()}] ⚠ афоризм не отправлен {chat_id}")
        else:
            print(f"[{now_str()}] ⏭ афоризм не получен, пропуск")
    except Exception as e:
        print(f"[{now_str()}] ⚠ Ошибка афоризма: {e}")


# ==================== ОБРАБОТКА ВХОДЯЩИХ ====================

def handle_incoming(msg):
    global total_received, total_skipped

    msg_id = msg.get("idMessage")
    chat_id = msg.get("chatId")
    text = (msg.get("textMessage") or "").strip()
    
    attachments_raw = msg.get("attachments") or []
    attachments_json = None
    if attachments_raw:
        attachments_json = json.dumps(attachments_raw, ensure_ascii=False)

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

    if attachments_raw:
        types = [a.get("type", "?") for a in attachments_raw]
        print(f"[{now_str()}] 📎 вложения: {types}")

    # 1. Запрос к Hermes (только админ, с префиксом)
    if chat_id == ADMIN_CHAT_ID:
        for prefix in HERMES_PREFIXES:
            if text.startswith(prefix):
                db.insert_message(chat_id, msg_id, text, TYPE_HERMES_REQ, attachments=attachments_json)
                _link_if_unanswered(chat_id, msg_id)
                print(f"[{now_str()}] 📝 TypeID=5 (запрос к Hermes)")
                return

    # 2. Ответ на утреннее приветствие?
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    last_morning = db.get_last_by_type(chat_id, TYPE_MORNING, since_datetime=today_start)

    if last_morning and not db.has_rel_by_for(chat_id, last_morning["mid"]):
        db.insert_message(chat_id, msg_id, text, TYPE_ANSWER, attachments=attachments_json)
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=last_morning["mid"],
            id_message_back=msg_id,
        )
        print(f"[{now_str()}] 📝 TypeID=1 (ответ на утреннее), связка: "
              f"{last_morning['mid']} → {msg_id}")
        return

    # 3. Всё остальное — служебное
    print(f"[{now_str()}] ⏭ {chat_id}: вне цикла, ответ не нужен")
    db.insert_message(chat_id, msg_id, text, TYPE_SERVICE, attachments=attachments_json)
    total_skipped += 1


def _link_if_unanswered(chat_id, msg_id):
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    last_morning = db.get_last_by_type(chat_id, TYPE_MORNING, since_datetime=today_start)
    if last_morning and not db.has_rel_by_for(chat_id, last_morning["mid"]):
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=last_morning["mid"],
            id_message_back=msg_id,
        )
        return True
    return False


# ==================== ОБРАБОТЧИКИ ПО TYPEID ====================

def process_type_0_1(chat_id, morning_msg):
    morning_id = morning_msg.get("mid") or morning_msg.get("id_message")
    info = ALLOWED_CHATS.get(chat_id, {})
    name = info.get("name", chat_id)

    rel = db.get_rel_by_for(chat_id, morning_id)

    if rel and rel.get("id_message_back"):
        answer_mid = rel["id_message_back"]
        answer_msg = db.get_message_by_id(chat_id, answer_mid)

        if answer_msg and answer_msg.get("type_id") == TYPE_ANSWER:
            if db.has_rel_by_for(chat_id, answer_mid):
                return

            pool = get_messages_for(chat_id, "ANSWER_MESSAGES")
            if not pool:
                print(f"[{now_str()}] ⚠ {chat_id}: пустой ANSWER_MESSAGES")
                return
            text = random.choice(pool)
            ok, wish_id = send(chat_id, text)
            if not ok or not wish_id:
                print(f"[{now_str()}] ⚠ пожелание не отправлено {chat_id} — помечаю failed")
                db.insert_rel(
                    chat_id=chat_id,
                    id_message_for=answer_mid,
                    id_message_back=f"failed_wish_{answer_mid}",
                )
                return

            db.insert_message(chat_id, wish_id, text, TYPE_WISH)
            db.insert_rel(
                chat_id=chat_id,
                id_message_for=answer_mid,
                id_message_back=wish_id,
            )
            global total_wishes
            total_wishes += 1
            print(f"[{now_str()}] 💬 пожелание отправлено {chat_id}")

            _send_weather(chat_id)
            _send_aphorism(chat_id)
            return

    # Нет ответа — warning
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
            print(f"[{now_str()}] ⚠ warning не отправлен {chat_id} — помечаю failed")
            db.insert_rel(
                chat_id=chat_id,
                id_message_for=morning_id,
                id_message_back=f"failed_warning_{morning_id}",
            )
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


def process_type_5(chat_id, req_msg):
    req_id = req_msg.get("mid") or req_msg.get("id_message")
    text = req_msg.get("text") or req_msg.get("message_text") or ""

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
        print(f"[{now_str()}] ⚠ ⏳ не отправлен {chat_id} — помечаю failed")
        db.insert_rel(
            chat_id=chat_id,
            id_message_for=req_id,
            id_message_back=f"failed_think_{req_id}",
        )
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
    global total_hermes

    if question.startswith("-command "):
        shell_cmd = question[len("-command "):].strip()
        answer, error = run_hermes_shell(shell_cmd)
    else:
        answer, error = ask_hermes(chat_id, question)

    total_hermes += 1

    if error:
        final_text = HERMES_ERROR_MSG
        print(f"[{now_str()}] ❌ Hermes ошибка: {error}")
    else:
        final_text = answer
        print(f"[{now_str()}] ✅ Hermes ответил ({len(answer)} симв.)")

    if think_id:
        first_part = final_text[:4000]
        if edit_message(chat_id, think_id, first_part):
            db.update_message_text(chat_id, think_id, first_part)
            # ⬅️ УБРАЛИ insert_message(_ans) + insert_rel
            # Связку think_id → ответ НЕ создаём: think_id сам стал ответом
            print(f"[{now_str()}] ✏️ отредактировано (in-place)")
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
                        print(f"[{now_str()}] ⚠ утреннее не отправлено {chat_id}")

            time.sleep(60)
        except Exception as e:
            print(f"[{now_str()}] ⚠ daily_worker error: {e}")
            time.sleep(60)


def alert_worker():
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
    print(f"[{now_str()}] 🤖 MAX Bot запущен")
    print(f"[{now_str()}] 📡 API: {MAX_API_BASE}")
    print(f"[{now_str()}] 👥 Чаты: {list(ALLOWED_CHATS.keys())}")
    print(f"[{now_str()}] 🛡 Админ: {ADMIN_CHAT_ID} ({ADMIN_NAME})")

    print_hermes_status()

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

    while True:
        try:
            for msg in get_messages():
                try:
                    handle_incoming(msg)
                except Exception as e:
                    print(f"[{now_str()}] ⚠ handle_incoming error: {e}")

            heartbeat()
        except Exception as e:
            print(f"[{now_str()}] ⚠ main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()