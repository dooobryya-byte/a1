# web/app.py
import os
import sys
import json
import time
import mimetypes
from typing import List

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


# Фильтр fromjson для Jinja2 (парсит JSON-строку в список)
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
    """Формат даты: сегодня — HH:MM, иначе — DD.MM HH:MM."""
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
    """Полная дата YYYY-MM-DD HH:MM:SS."""
    if not s:
        return ""
    return s[:19]


def initials(name):
    """Инициалы для аватара: 'Иван Петров' → 'ИП', 'Иван' → 'ИВ'."""
    if not name:
        return "?"
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def short_mid(mid):
    """Короткий mid для отображения."""
    if not mid:
        return ""
    if len(mid) <= 12:
        return mid
    return mid[-8:]


def _get_upload_type(filename, content_type):
    """Определяет тип вложения по MIME-типу: image/video/audio/file."""
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
    """Главная страница: список чатов + первый/выбранный чат."""
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
    """Страница конкретного чата по user_id."""
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


@app.get("/chat/{user_id}/partial", response_class=HTMLResponse)
def chat_partial(request: Request, user_id: str):
    """Возвращает только HTML сообщений и шапки (без base.html).
    Для AJAX-навигации между чатами без перезагрузки страницы."""
    active_chat = repository.get_chat_by_user(user_id)
    if not active_chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    messages = repository.get_messages(active_chat["id"], limit=100)

    return templates.TemplateResponse(request, "chat_partial.html", {
        "active_chat": active_chat,
        "messages": messages,
        "format_dt": format_dt,
        "initials": initials,
        "short_mid": short_mid,
        "admin_chat_id": str(ADMIN_CHAT_ID),
        # ⬅️ ГЛАВНОЕ: allowed_chats для AJAX
        "allowed_chats": _chats_for_forward(active_chat["user_id"]),
    })

@app.get("/chat/{user_id}/messages.json")
def chat_messages_json(user_id: str, after_id: int = 0):
    """JSON с сообщениями после указанного ID.
    Для auto-refresh в веб-UI (каждые 15 сек)."""
    chat = repository.get_chat_by_user(user_id)
    if not chat:
        return JSONResponse({"ok": False, "error": "chat not found"}, status_code=404)

    all_messages = repository.get_messages(chat["id"], limit=500)
    new_messages = [m for m in all_messages if (m.get("id") or 0) > after_id]

    result = []
    for m in new_messages:
        attachments = []
        if m.get("attachments"):
            try:
                attachments = json.loads(m["attachments"])
            except Exception:
                attachments = []

        result.append({
            "id": m.get("id"),
            "mid": m.get("mid"),
            "direction": m.get("direction"),
            "author": m.get("author"),
            "sender_name": m.get("sender_name"),
            "text": m.get("text") or "",
            "created_at": m.get("created_at"),
            "created_at_fmt": format_dt(m.get("created_at")),
            "edited_at": m.get("edited_at"),
            "attachments": attachments,
        })

    return JSONResponse({
        "ok": True,
        "chat_id": chat["id"],
        "user_id": user_id,
        "count": len(result),
        "messages": result,
    })


@app.post("/chat/{user_id}/send")
def send_message(user_id: str, text: str = Form("")):
    """Отправка текстового сообщения через MAX API."""
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
    files: List[UploadFile] = FastFile([]),
    existing_tokens: str = Form("[]"),
    caption: str = Form(""),
    is_edit: str = Form("0"),
):
    """Загрузка и отправка вложений через MAX API.

    Логика:
    - existing_tokens — готовые вложения (при редактировании)
    - 1 файл → одно сообщение с caption
    - Несколько файлов + текст → сначала текст, потом вложения
    - file → по одному
    - image/video → пачкой (до 12)
    """
    import traceback
    import json as _json
    try:
        caption = (caption or "").strip()

        try:
            existing = _json.loads(existing_tokens or "[]")
        except _json.JSONDecodeError:
            existing = []

        is_edit_mode = is_edit == "1"
        print(f"[web] 📦 attach: {len(files)} файлов, "
              f"{len(existing)} existing, edit={is_edit_mode}")

        # Группируем по upload_type
        groups = {}  # upload_type → [files]
        for f in files:
            ct = (f.content_type or "").lower()
            filename = f.filename or ""
            upload_type = _get_upload_type(filename, ct)
            groups.setdefault(upload_type, []).append(f)

        total_files = sum(len(v) for v in groups.values())
        if groups:
            print(f"[web] 📦 группы: " + ", ".join(
                f"{k}={len(v)}" for k, v in groups.items()
            ))

        # ═══ Если только existing (без новых файлов) — один batch ═══
        if existing and not groups:
            print(f"[web] 📦 только existing: {len(existing)} вложений")
            resp = await _send_attachment_impl_batch(
                user_id, [], existing=existing, caption=caption
            )
            return resp

        results = []
        caption_used = False
        existing_used = False

        # ═══ Логика caption ═══
        # Если несколько файлов + текст — сначала отдельное текстовое.
        
        # ⬅️ Текст отдельно — ТОЛЬКО для документов (file/audio)
        # Для картинок/видео — всё в одном сообщении (MAX поддерживает)
        has_only_media = all(
            t in ("image", "video") for t in groups.keys()
        )
        send_caption_separately = (
            not is_edit_mode
            and not has_only_media             # ⬅️ не разделяем для медиа
            and (total_files + len(existing)) > 1
            and caption
        )        
        if send_caption_separately:
            print(f"[web] 📝 отправляем текст отдельным сообщением")
            await _send_text_message(user_id, caption)
            caption = ""

        # ═══ Отправка вложений ═══
        order = ["image", "video", "audio", "file"]
        for upload_type in order:
            if upload_type not in groups:
                continue

            group_files = groups[upload_type]

            # file/audio — по одному
            if upload_type in ("file", "audio"):
                for f in group_files:
                    cap = caption if not caption_used else ""
                    # ⬅️ Существующие вложения идут с первым сообщением
                    ex = existing if not existing_used else []
                    resp = await _send_attachment_impl_batch(
                        user_id, [f], existing=ex, caption=cap
                    )
                    results.append(resp)
                    caption_used = True
                    existing_used = True
            else:
                cap = caption if not caption_used else ""
                ex = existing if not existing_used else []
                resp = await _send_attachment_impl_batch(
                    user_id, group_files, existing=ex, caption=cap
                )
                results.append(resp)
                caption_used = True
                existing_used = True

        # ═══ Если existing остались (не было новых файлов) ═══
        if existing and not existing_used:
            resp = await _send_attachment_impl_batch(
                user_id, [], existing=existing, caption=caption
            )
            results.append(resp)

        return JSONResponse({"ok": True, "groups": len(results)})
    except Exception as e:
        print(f"[web] ❌❌❌ ATTACH ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(
            {"ok": False, "error": f"{type(e).__name__}: {e}"},
            status_code=500,
        )

async def _send_attachment_impl(user_id, file, caption):
    """Реализация загрузки вложения: upload → send → enrich url → save."""
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

    # 1. POST /uploads — получить upload_url
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

    # 2. POST upload_url — залить файл
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

    # 3. POST /messages — retry на attachment.not.ready
    attachments = [{
        "type": upload_type,
        "payload": {"token": upload_token},
    }]
    payload = {
        "text": caption or None,
        "attachments": attachments,
    }

    mid = None
    retry_delays = [1.0, 2.0, 4.0, 8.0]

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
                continue

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

    # 4. Запись в БД
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

    # 5. Enrich url через GET /messages?message_ids
    try:
        time.sleep(1.0)
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

async def _send_attachment_impl_batch(user_id, files, existing=None, caption=""):
    """Отправка нескольких вложений ОДНИМ сообщением.

    existing — список готовых вложений с токенами (не загружаются заново).
    files — новые файлы для загрузки.
    caption — текст сообщения.
    """
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    caption = (caption or "").strip()
    existing = existing or []

    if not files and not existing:
        return JSONResponse({"ok": False, "error": "no files"}, status_code=400)

    # ═══ ЭТАП 0: Готовые токены (существующие вложения) ═══
    attachments = []
    uploaded_info = []

    for att in existing:
        token = att.get("token")
        if not token:
            continue
        att_type = att.get("type", "image")
        attachments.append({
            "type": att_type,
            "payload": {"token": token},
        })
        uploaded_info.append({
            "type": att_type,
            "filename": att.get("filename", "file"),
            "token": token,
            "url": att.get("url"),
            "photo_id": att.get("photo_id"),
        })

    print(f"[web] 📦 existing: {len(attachments)} вложений из токенов")

    # ═══ ЭТАП 1: Загрузить новые файлы ═══
    for file in (files or []):
        file_bytes = await file.read()
        if not file_bytes:
            print(f"[web] ⚠ пустой файл: {file.filename}")
            continue

        filename = file.filename or "file"
        content_type = (
            file.content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        upload_type = _get_upload_type(filename, content_type)

        print(f"[web] 📎 batch upload: {filename} ({content_type}) → {upload_type}")

        # 1.1 POST /uploads — получить upload_url
        try:
            r = requests.post(
                f"{MAX_API_BASE}/uploads",
                params={"type": upload_type},
                headers={"Authorization": MAX_BOT_TOKEN},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"[web] ⚠ uploads error: {r.status_code} {r.text[:200]}")
                continue
            upload_data = r.json()
            upload_url = upload_data.get("url")
            upload_token = upload_data.get("token")
        except Exception as e:
            print(f"[web] ⚠ uploads exception: {e}")
            continue

        if not upload_url:
            print(f"[web] ⚠ no upload url for {filename}")
            continue

        # 1.2 POST upload_url — залить файл
        try:
            files_data = {"data": (filename, file_bytes, content_type)}
            r = requests.post(upload_url, files=files_data, timeout=60)
            if r.status_code not in (200, 201):
                print(f"[web] ⚠ upload error: {r.status_code} {r.text[:200]}")
                continue

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
        except Exception as e:
            print(f"[web] ⚠ upload exception: {e}")
            continue

        if not upload_token:
            print(f"[web] ⚠ no token for {filename}")
            continue

        # 1.3 Добавить в attachments
        attachments.append({
            "type": upload_type,
            "payload": {"token": upload_token},
        })
        uploaded_info.append({
            "type": upload_type,
            "filename": filename,
            "token": upload_token,
        })

    if not attachments:
        return JSONResponse(
            {"ok": False, "error": "ни один файл не загружен"},
            status_code=400,
        )

    print(f"[web] 📦 batch: {len(attachments)} вложений готовы к отправке")

    # ═══ ЭТАП 2: POST /messages — ОДНО сообщение с несколькими attachments ═══
    payload = {
        "text": caption or None,
        "attachments": attachments,
    }

    mid = None
    retry_delays = [1.0, 2.0, 4.0, 8.0]

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
            print(f"[web] 🔍 batch send (attempt {attempt+1}): status={r.status_code} "
                  f"body={r.text[:300]!r}")

            if r.status_code == 200:
                data = r.json()
                mid = ((data.get("message") or {}).get("body") or {}).get("mid")
                break

            if r.status_code == 400 and "attachment.not.ready" in r.text:
                continue

            return JSONResponse(
                {"ok": False, "error": f"send: {r.status_code} {r.text[:200]}"},
                status_code=400,
            )
        except Exception as e:
            print(f"[web] ⚠ batch send error: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    if not mid:
        return JSONResponse(
            {"ok": False, "error": "attachment.not.ready after retries"},
            status_code=400,
        )

    # ═══ ЭТАП 3: Запись в БД — ОДНА запись с несколькими вложениями ═══
    attachments_json = json.dumps(uploaded_info, ensure_ascii=False)

    try:
        repository.save_message(
            user_id=user_id, mid=mid,
            text=caption or "",
            direction="out", author="admin", is_bot=True, type_id=9,
            attachments=attachments_json,
        )
    except Exception as e:
        print(f"[web] ⚠ save_message (batch): {e}")

    # ═══ ЭТАП 4: Enrich url через GET /messages?message_ids ═══
    try:
        time.sleep(1.0)
        r2 = requests.get(
            f"{MAX_API_BASE}/messages",
            params={"message_ids": mid},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=15,
        )
        print(f"[web] 🔍 enrich batch: status={r2.status_code}")
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
                        # имя файла из uploaded_info (по индексу)
                        idx = len(enriched)
                        if idx < len(uploaded_info):
                            clean["filename"] = uploaded_info[idx]["filename"]
                        enriched.append(clean)
                    enriched_json = json.dumps(enriched, ensure_ascii=False)
                    repository.update_attachments(mid, enriched_json)
                    print(f"[web] 🔍 обогащено batch: {enriched_json[:200]}")
    except Exception as e:
        print(f"[web] ⚠ enrich batch error: {e}")

    print(f"[web] ✅ batch вложений отправлено {user_id}: "
          f"{len(uploaded_info)} файлов, mid={mid}")
    return JSONResponse({
        "ok": True,
        "mid": mid,
        "files": uploaded_info,
    })

async def _send_text_message(user_id: str, text: str):
    """Отправка текстового сообщения без вложений."""
    import requests
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    if not text.strip():
        return None

    payload = {"text": text}

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
        print(f"[web] 🔍 send text: status={r.status_code} body={r.text[:200]!r}")

        if r.status_code == 200:
            data = r.json()
            mid = ((data.get("message") or {}).get("body") or {}).get("mid")
            # Сохраняем в БД
            try:
                repository.save_message(
                    user_id=user_id, mid=mid,
                    text=text,
                    direction="out", author="admin", is_bot=True,
                    type_id=1,  # текстовое сообщение
                )
            except Exception as e:
                print(f"[web] ⚠ save text message: {e}")
            return mid
        else:
            print(f"[web] ⚠ send text error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[web] ⚠ send text exception: {e}")

    return None

@app.delete("/message/{mid}")
def delete_message(mid: str):
    """Удаление сообщения: soft-delete в БД + DELETE в MAX."""
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
async def edit_message_route(
    mid: str,
    text: str = Form(""),
    existing_tokens: str = Form("[]"),
    files: List[UploadFile] = FastFile([]),
):
    """Редактирование сообщения: PUT в MAX + update в БД.

    Пустой text допустим, если есть вложения.
    """
    import requests
    import json as _json
    from config import MAX_BOT_TOKEN, MAX_API_BASE

    text = (text or "").strip()

    msg = repository.get_message_by_mid(mid)
    if not msg:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    # ⬅️ Парсим существующие вложения
    try:
        existing = _json.loads(existing_tokens or "[]")
    except _json.JSONDecodeError:
        existing = []

    # ⬅️ Загружаем новые файлы
    attachments = []
    for att in existing:
        token = att.get("token")
        if token:
            attachments.append({
                "type": att.get("type", "image"),
                "payload": {"token": token},
            })

    for file in files:
        file_bytes = await file.read()
        if not file_bytes:
            continue

        filename = file.filename or "file"
        content_type = (
            file.content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        upload_type = _get_upload_type(filename, content_type)

        # Загрузка файла в MAX
        try:
            r = requests.post(
                f"{MAX_API_BASE}/uploads",
                params={"type": upload_type},
                headers={"Authorization": MAX_BOT_TOKEN},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            upload_data = r.json()
            upload_url = upload_data.get("url")
            upload_token = upload_data.get("token")

            files_data = {"data": (filename, file_bytes, content_type)}
            r = requests.post(upload_url, files=files_data, timeout=60)
            if r.status_code not in (200, 201):
                continue

            if not upload_token:
                try:
                    res = r.json()
                    if res.get("photos"):
                        first = next(iter(res["photos"].values()))
                        upload_token = first.get("token") if isinstance(first, dict) else first
                except Exception:
                    pass

            if upload_token:
                attachments.append({
                    "type": upload_type,
                    "payload": {"token": upload_token},
                })
        except Exception as e:
            print(f"[web] ⚠ upload error: {e}")
            continue

    # ⬅️ Пустой текст допустим, если есть вложения
    if not text and not attachments:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    # ⬅️ PUT в MAX с вложениями
    # ВАЖНО: всегда передаём attachments (даже пустой массив),
    # чтобы MAX удалил вложения при их удалении
    try:
        payload = {
            "text": text or None,
            "attachments": attachments,      # ⬅️ ВСЕГДА
        }

        r = requests.put(
            f"{MAX_API_BASE}/messages",
            params={"message_id": mid},
            headers={
                "Authorization": MAX_BOT_TOKEN,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[web] ⚠ MAX PUT: {r.status_code} {r.text[:200]}")
            return JSONResponse(
                {"ok": False, "error": f"MAX: {r.status_code}"},
                status_code=400,
            )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # ⬅️ Обновляем в БД
    # ⬅️ ВСЕГДА сохраняем (даже пустой массив), чтобы картинка удалилась
    attachments_json = _json.dumps(
        [{"type": a["type"], "token": a["payload"]["token"]} for a in attachments],
        ensure_ascii=False,
    )

    ok = repository.edit_message(mid, text, attachments_json)
    if not ok:
        return JSONResponse({"ok": False, "error": "db error"}, status_code=500)

    # ⬅️ Enrich url с retry (MAX генерирует url асинхронно)
    try:
        enriched_json = None
        for attempt in range(5):
            time.sleep(1.5)
            r2 = requests.get(
                f"{MAX_API_BASE}/messages",
                params={"message_ids": mid},
                headers={"Authorization": MAX_BOT_TOKEN},
                timeout=15,
            )
            if r2.status_code != 200:
                print(f"[web] ⚠ enrich edit: HTTP {r2.status_code} attempt {attempt+1}")
                continue

            msgs = r2.json().get("messages", [])
            if not msgs:
                print(f"[web] ⏳ enrich edit: пусто messages, attempt {attempt+1}")
                continue

            body = msgs[0].get("body") or {}
            max_atts = body.get("attachments") or []

            # ⬅️ Если вложений нет — сохраняем "[]" (все удалены)
            if not max_atts:
                if not attachments:
                    # Мы сами удалили все вложения — сохраняем пустой массив
                    repository.update_attachments(mid, "[]")
                    print(f"[web] ✅ enrich edit: все вложения удалены, БД обновлена")
                else:
                    print(f"[web] ⏳ enrich edit: пусто, attempt {attempt+1}")
                break

            # Проверяем, есть ли url у всех
            has_all_urls = all(
                (a.get("payload") or {}).get("url") for a in max_atts
            )
            if not has_all_urls:
                print(f"[web] ⏳ enrich edit: url не готов, attempt {attempt+1}")
                continue

            # Собираем enriched (без обращения к msg["attachments"])
            enriched = []
            for a in max_atts:
                clean = {"type": a.get("type")}
                payload = a.get("payload") or {}
                if payload.get("url"): clean["url"] = payload["url"]
                if payload.get("token"): clean["token"] = payload["token"]
                if payload.get("photo_id"): clean["photo_id"] = payload["photo_id"]
                # filename по индексу из uploaded_info (attachments)
                idx = len(enriched)
                if idx < len(attachments):
                    clean["filename"] = "image"
                else:
                    clean["filename"] = "image"
                enriched.append(clean)

            enriched_json = _json.dumps(enriched, ensure_ascii=False)
            print(f"[web] ✅ enrich edit: {len(enriched)} вложений, attempt {attempt+1}")
            break

        if enriched_json:
            repository.update_attachments(mid, enriched_json)
        # Если enriched_json = None и max_atts пусто — уже сохранили "[]"
    except Exception as e:
        print(f"[web] ⚠ enrich edit error: {e}")
        
    print(f"[web] ✅ отредактировано: mid={mid}, "
          f"text={len(text)} симв., attachments={len(attachments)}")
    return JSONResponse({"ok": True, "mid": mid, "text": text, "attachments": attachments})    

@app.post("/chat/{user_id}/sync")
def chat_sync(user_id: str):
    """Двусторонняя синхронизация чата с MAX (по кнопке 🔄)."""
    result = sync_chat(user_id)
    return JSONResponse(result)


@app.get("/health")
def health():
    """Проверка живости сервиса."""
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

        # Сохраняем attachments
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