# web/app.py
import os
import sys
import json
import time
import mimetypes
from datetime import datetime
from config import ALLOWED_CHATS, ADMIN_CHAT_ID

from fastapi import (
    FastAPI, Request, HTTPException, Form,
    UploadFile, File as FastFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Корень проекта в sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared import repository


# ==================== FastAPI ====================

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["root_path"] = "/max"


# ⬅️ Фильтр fromjson для Jinja2
def _fromjson(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


templates.env.filters["fromjson"] = _fromjson


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static",
)


# ==================== Утилиты ====================

def format_dt(s):
    if not s:
        return ""
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return s[:16] if s else ""


def format_dt_full(s):
    if not s:
        return ""
    return s[:19]


def initials(name):
    if not name:
        return "?"
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def short_mid(mid):
    if not mid:
        return ""
    if len(mid) <= 12:
        return mid
    return mid[-8:]


def _get_upload_type(filename, content_type):
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    return "file"


def _chats_for_forward(current_user_id: str) -> list[dict]:
    """Список чатов для пересылки (все, кроме текущего)."""
    result = []
    for cid, info in ALLOWED_CHATS.items():
        if str(cid) == str(current_user_id):
            continue
        result.append({
            "user_id": str(cid),
            "name": info.get("name", str(cid)),
        })
    return result

# ==================== Роуты ====================

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    chats = repository.list_chats()

    if not chats:
        return templates.TemplateResponse(request, "index.html", {
            "chats": [], "active_chat": None, "messages": [],
            "format_dt": format_dt, "format_dt_full": format_dt_full,
            "initials": initials, "short_mid": short_mid,
            "admin_chat_id": str(ADMIN_CHAT_ID),
        })

    active_user_id = request.query_params.get("chat")
    active_chat = None
    if active_user_id:
        active_chat = repository.get_chat_by_user(active_user_id)
    if not active_chat:
        active_chat = chats[0]

    messages = repository.get_messages(active_chat["id"], limit=100) if active_chat else []

    return templates.TemplateResponse(request, "index.html", {
        "chats": chats, "active_chat": active_chat, "messages": messages,
        "format_dt": format_dt, "format_dt_full": format_dt_full,
        "initials": initials, "short_mid": short_mid,
        "allowed_chats": _chats_for_forward(active_chat["user_id"]) if active_chat else [],
        "admin_chat_id": str(ADMIN_CHAT_ID),
    })


@app.get("/chat/{user_id}", response_class=HTMLResponse)
def chat_view(request: Request, user_id: str):
    chats = repository.list_chats()
    active_chat = repository.get_chat_by_user(user_id)
    if not active_chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    messages = repository.get_messages(active_chat["id"], limit=100)

    return templates.TemplateResponse(request, "index.html", {
        "chats": chats, "active_chat": active_chat, "messages": messages,
        "format_dt": format_dt, "format_dt_full": format_dt_full,
        "initials": initials, "short_mid": short_mid,
        "allowed_chats": _chats_for_forward(active_chat["user_id"]) if active_chat else [],
        "admin_chat_id": str(ADMIN_CHAT_ID),
    })


@app.post("/chat/{user_id}/send")
def send_message(user_id: str, text: str = Form("")):
    text = (text or "").strip()
    if not text:
        return RedirectResponse(url=f"/max/chat/{user_id}", status_code=303)

    try:
        from bot import send as bot_send
        ok, mid = bot_send(user_id, text)
    except Exception as e:
        print(f"[web] ❌ bot.send error: {e}")
        return RedirectResponse(url=f"/max/chat/{user_id}", status_code=303)

    if not ok or not mid:
        print(f"[web] ❌ не удалось отправить {user_id}: {text[:60]}")
        return RedirectResponse(url=f"/max/chat/{user_id}", status_code=303)

    try:
        repository.save_message(
            user_id=user_id, mid=mid, text=text,
            direction="out", author="admin", is_bot=True, type_id=9,
        )
    except Exception as e:
        print(f"[web] ⚠ save_message: {e}")

    print(f"[web] ✅ отправлено {user_id}: {text[:60]} (mid={mid})")
    return RedirectResponse(url=f"/max/chat/{user_id}", status_code=303)


@app.post("/chat/{user_id}/attach")
async def send_attachment(
    user_id: str,
    file: UploadFile = FastFile(...),
    caption: str = Form(""),
):
    import traceback
    try:
        return await _send_attachment_impl(user_id, file, caption)
    except Exception as e:
        print(f"[web] ❌❌❌ ATTACH ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(
            {"ok": False, "error": f"{type(e).__name__}: {e}"},
            status_code=500,
        )


async def _send_attachment_impl(user_id, file, caption):
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    caption = (caption or "").strip()

    file_bytes = await file.read()
    if not file_bytes:
        return JSONResponse({"ok": False, "error": "empty file"}, status_code=400)

    filename = file.filename or "file"
    content_type = (
        file.content_type
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    upload_type = _get_upload_type(filename, content_type)

    print(f"[web] 📎 attach: {filename} ({content_type}) → {upload_type}, "
          f"{len(file_bytes)} байт")

    # 1. POST /uploads
    try:
        r = requests.post(
            f"{MAX_API_BASE}/uploads",
            params={"type": upload_type},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=15,
        )
        print(f"[web] 🔍 uploads: status={r.status_code} body={r.text[:300]!r}")
        if r.status_code != 200:
            return JSONResponse(
                {"ok": False, "error": f"uploads: {r.status_code} {r.text[:200]}"},
                status_code=400,
            )
        upload_data = r.json()
        upload_url = upload_data.get("url")
        upload_token = upload_data.get("token")
    except Exception as e:
        print(f"[web] ⚠ uploads error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    if not upload_url:
        return JSONResponse({"ok": False, "error": "no upload url"}, status_code=500)

    # 2. POST upload_url с файлом
    try:
        files = {"data": (filename, file_bytes, content_type)}
        r = requests.post(upload_url, files=files, timeout=60)
        print(f"[web] 🔍 upload: status={r.status_code} body={r.text[:500]!r}")
        if r.status_code not in (200, 201):
            return JSONResponse(
                {"ok": False, "error": f"upload: {r.status_code} {r.text[:200]}"},
                status_code=400,
            )

        if not upload_token:
            try:
                upload_result = r.json()
            except Exception:
                upload_result = {}

            if upload_result.get("photos"):
                photos = upload_result["photos"]
                first = next(iter(photos.values()))
                if isinstance(first, dict):
                    upload_token = first.get("token")
                else:
                    upload_token = first
            elif upload_result.get("token"):
                upload_token = upload_result.get("token")
            elif upload_result.get("fileId"):
                upload_token = upload_result.get("fileId")

            print(f"[web] 🔍 extracted token: {upload_token!r}")

    except Exception as e:
        print(f"[web] ⚠ upload error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    if not upload_token:
        return JSONResponse({"ok": False, "error": "no token after upload"}, status_code=500)

    # ⬅️ НОВОЕ: MAX обрабатывает файл асинхронно. Даже 16-байтовый test.txt
    # не готов мгновенно. Ждём + retry на attachment.not.ready.
    attachments = [{
        "type": upload_type,
        "payload": {"token": upload_token},
    }]
    payload = {
        "text": caption or None,
        "attachments": attachments,
    }

    mid = None
    retry_delays = [1.0, 2.0, 4.0, 8.0]  # 4 попытки, экспоненциально

    for attempt, delay in enumerate([0.0] + retry_delays):
        if delay:
            print(f"[web] ⏳ attachment.not.ready, ждём {delay} сек (попытка {attempt+1})...")
            time.sleep(delay)

        try:
            r = requests.post(
                f"{MAX_API_BASE}/messages",
                params={"user_id": user_id},
                headers={
                    "Authorization": MAX_BOT_TOKEN,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            print(f"[web] 🔍 send (attempt {attempt+1}): status={r.status_code} "
                  f"body={r.text[:300]!r}")

            if r.status_code == 200:
                data = r.json()
                mid = ((data.get("message") or {}).get("body") or {}).get("mid")
                break

            if r.status_code == 400 and "attachment.not.ready" in r.text:
                continue  # retry

            # другая ошибка — выходим
            return JSONResponse(
                {"ok": False, "error": f"send: {r.status_code} {r.text[:200]}"},
                status_code=400,
            )
        except Exception as e:
            print(f"[web] ⚠ send attach error: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    if not mid:
        return JSONResponse(
            {"ok": False, "error": "attachment.not.ready after retries"},
            status_code=400,
        )

    # 4. Запись в БД с attachments
    attachments_json = json.dumps([{
        "type": upload_type,
        "filename": filename,
        "token": upload_token,
    }], ensure_ascii=False)

    try:
        repository.save_message(
            user_id=user_id, mid=mid,
            text=caption or "",
            direction="out", author="admin", is_bot=True, type_id=9,
            attachments=attachments_json,
        )
    except Exception as e:
        print(f"[web] ⚠ save_message (attach): {e}")

    # ⬅️ НОВОЕ: получить url из MAX и обновить attachments.
    # MAX отдаёт url только через GET /messages?message_ids=<mid>
    try:
        time.sleep(1.0)  # дать MAX обработать
        r2 = requests.get(
            f"{MAX_API_BASE}/messages",
            params={"message_ids": mid},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=15,
        )
        print(f"[web] 🔍 enrich: status={r2.status_code}")
        if r2.status_code == 200:
            msgs = r2.json().get("messages", [])
            if msgs:
                body = msgs[0].get("body") or {}
                max_atts = body.get("attachments") or []
                if max_atts:
                    enriched = []
                    for a in max_atts:
                        clean = {"type": a.get("type")}
                        payload = a.get("payload") or {}
                        if payload.get("url"):
                            clean["url"] = payload["url"]
                        if payload.get("token"):
                            clean["token"] = payload["token"]
                        if payload.get("photo_id"):
                            clean["photo_id"] = payload["photo_id"]
                        clean["filename"] = filename
                        enriched.append(clean)
                    enriched_json = json.dumps(enriched, ensure_ascii=False)
                    repository.update_attachments(mid, enriched_json)
                    print(f"[web] 🔍 обогащено: {enriched_json[:200]}")
                else:
                    print(f"[web] ⚠ enrich: attachments пусты в ответе MAX")
    except Exception as e:
        print(f"[web] ⚠ enrich error: {e}")

    print(f"[web] ✅ вложение отправлено {user_id}: {filename} "
          f"({upload_type}) mid={mid}")
    return JSONResponse({"ok": True, "mid": mid, "filename": filename})


@app.delete("/message/{mid}")
def delete_message(mid: str):
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    msg = repository.get_message_by_mid(mid)
    if not msg:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    ok = repository.delete_message(mid)
    if not ok:
        return JSONResponse({"ok": False, "error": "db error"}, status_code=500)

    try:
        r = requests.delete(
            f"{MAX_API_BASE}/messages",
            params={"message_id": mid},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=10,
        )
        if r.status_code == 200:
            print(f"[web] ✅ удалено в MAX: {mid}")
        else:
            print(f"[web] ⚠ MAX: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"[web] ⚠ MAX delete error: {e}")

    print(f"[web] 🗑 удалено локально: {mid}")
    return JSONResponse({"ok": True})


@app.put("/message/{mid}")
def edit_message_route(mid: str, text: str = Form("")):
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    text = (text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    msg = repository.get_message_by_mid(mid)
    if not msg:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    try:
        r = requests.put(
            f"{MAX_API_BASE}/messages",
            params={"message_id": mid},
            headers={
                "Authorization": MAX_BOT_TOKEN,
                "Content-Type": "application/json",
            },
            json={"text": text},
            timeout=10,
        )
        if r.status_code == 200:
            print(f"[web] ✅ отредактировано в MAX: {mid}")
        else:
            print(f"[web] ⚠ MAX PUT: {r.status_code} {r.text[:100]}")
            return JSONResponse(
                {"ok": False, "error": f"MAX: {r.status_code}"},
                status_code=400,
            )
    except Exception as e:
        print(f"[web] ⚠ MAX PUT error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    ok = repository.edit_message(mid, text)
    if not ok:
        return JSONResponse({"ok": False, "error": "db error"}, status_code=500)

    print(f"[web] ✏️ отредактировано локально: {mid}")
    return JSONResponse({"ok": True, "text": text})


@app.post("/chat/{user_id}/sync")
def chat_sync(user_id: str):
    """Двусторонняя синхронизация с MAX."""
    result = sync_chat(user_id)
    return JSONResponse(result)


@app.get("/health")
def health():
    return {"status": "ok", "chats": len(repository.list_chats())}


# ==================== Синхронизация ====================

def sync_chat(user_id: str, limit: int = 100) -> dict:
    """
    Двусторонняя синхронизация чата с MAX:
      1. Добавляет в БД сообщения, которых там нет.
      2. Помечает удалёнными те, которых нет в MAX.
    """
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    chat = repository.get_chat_by_user(user_id)
    if not chat:
        return {"ok": False, "error": "chat not found"}

    chat_id = chat.get("chat_id")
    if not chat_id:
        return {"ok": False, "error": "no chat_id"}

    # 1. Запросить последние N из MAX
    try:
        r = requests.get(
            f"{MAX_API_BASE}/messages",
            params={"chat_id": chat_id, "count": limit},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=15,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"MAX HTTP {r.status_code}"}
        max_messages = r.json().get("messages", [])
    except Exception as e:
        return {"ok": False, "error": str(e)}

    max_by_mid = {}
    for m in max_messages:
        body = m.get("body") or {}
        mid = body.get("mid")
        if mid:
            max_by_mid[mid] = m

    # 2. Запросить последние N из БД
    db_messages = repository.get_messages(chat["id"], limit=limit)
    db_by_mid = {m["mid"]: m for m in db_messages if m["mid"]}

    # 3. Добавить то, чего нет в БД
    added = 0
    for mid, m in max_by_mid.items():
        if mid in db_by_mid:
            continue
        if repository.get_message_by_mid(mid):
            continue

        body = m.get("body") or {}
        sender = m.get("sender") or {}

        text = body.get("text", "") or ""
        ts_ms = m.get("timestamp")
        is_bot = sender.get("is_bot", False)
        sender_id = str(sender.get("user_id") or "")
        sender_name = sender.get("name") or sender.get("first_name") or ""
        direction = "out" if is_bot else "in"
        author = "bot" if is_bot else "user"

        # ⬅️ Сохраняем attachments
        attachments_list = body.get("attachments") or []
        attachments_json = None
        if attachments_list:
            clean_attachments = []
            for a in attachments_list:
                clean = {"type": a.get("type")}
                payload = a.get("payload") or {}
                if payload.get("token"):
                    clean["token"] = payload.get("token")
                if payload.get("url"):
                    clean["url"] = payload.get("url")
                if payload.get("photo_id"):
                    clean["photo_id"] = payload.get("photo_id")
                if a.get("filename"):
                    clean["filename"] = a.get("filename")
                clean_attachments.append(clean)
            attachments_json = json.dumps(clean_attachments, ensure_ascii=False)

        if attachments_list and not text:
            types = [a.get("type", "file") for a in attachments_list]
            text = f"📎 [{', '.join(types)}]"

        created_at = None
        if ts_ms:
            created_at = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

        try:
            repository.save_message(
                user_id=user_id,
                mid=mid,
                text=text,
                direction=direction,
                author=author,
                is_bot=is_bot,
                chat_id=str(chat_id),
                sender_id=sender_id or None,
                sender_name=sender_name or None,
                timestamp_ms=ts_ms,
                created_at=created_at,
                type_id=9,
                attachments=attachments_json,
            )
            added += 1
            print(f"[sync] ➕ добавлено: {mid} ({direction}/{author}): {text[:40]}")
        except Exception as e:
            print(f"[sync] ⚠ add error {mid}: {e}")

    # 4. Пометить удалённые
    marked = 0
    for mid, m in db_by_mid.items():
        if mid in max_by_mid:
            continue
        if repository.delete_message(mid):
            marked += 1
            print(f"[sync] 🗑 помечено удалённым: {mid}")

    print(f"[sync] user={user_id}: "
          f"в MAX {len(max_by_mid)}, в БД было {len(db_by_mid)}, "
          f"добавлено {added}, удалено {marked}")

    return {
        "ok": True,
        "in_max": len(max_by_mid),
        "in_db_before": len(db_by_mid),
        "added": added,
        "marked": marked,
    }