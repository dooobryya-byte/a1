#!/usr/bin/env python3
"""
test_attach.py — тест загрузки и отправки вложения в MAX.

Использование:
    python test_attach.py <user_id> <path_to_file>
    python test_attach.py 8627605 /tmp/test.jpg
"""
import sys
import os
import mimetypes
import json
import requests

from config import MAX_BOT_TOKEN, MAX_API_BASE


def _get_upload_type(filename: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    return "file"


def main():
    if len(sys.argv) < 3:
        print("Использование: python test_attach.py <user_id> <path_to_file>")
        sys.exit(1)

    user_id = sys.argv[1]
    file_path = sys.argv[2]

    if not os.path.exists(file_path):
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    upload_type = _get_upload_type(filename, content_type)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    print("=" * 70)
    print(f"  📎 Тест вложения")
    print("=" * 70)
    print(f"  user_id:      {user_id}")
    print(f"  file:         {filename}")
    print(f"  content_type: {content_type}")
    print(f"  upload_type:  {upload_type}")
    print(f"  size:         {len(file_bytes)} байт")
    print()

    # ─── Шаг 1: POST /uploads ───
    print("─── Шаг 1: POST /uploads ───")
    try:
        r = requests.post(
            f"{MAX_API_BASE}/uploads",
            params={"type": upload_type},
            headers={"Authorization": MAX_BOT_TOKEN},
            timeout=15,
        )
        print(f"  HTTP: {r.status_code}")
        print(f"  Body: {r.text[:500]}")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        sys.exit(1)

    if r.status_code != 200:
        print("  ❌ Ошибка на шаге 1")
        sys.exit(1)

    try:
        upload_data = r.json()
    except Exception as e:
        print(f"  ❌ Не JSON: {e}")
        sys.exit(1)

    upload_url = upload_data.get("url")
    upload_token = upload_data.get("token")

    print(f"  url:   {upload_url!r}")
    print(f"  token: {upload_token!r}")
    print()

    if not upload_url:
        print("  ❌ Нет url")
        sys.exit(1)

    # ─── Шаг 2: POST upload_url с файлом ───
    print("─── Шаг 2: POST upload_url с файлом ───")
    try:
        files = {"data": (filename, file_bytes, content_type)}
        r = requests.post(upload_url, files=files, timeout=60)
        print(f"  HTTP: {r.status_code}")
        print(f"  Body: {r.text[:1000]}")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        sys.exit(1)

    if r.status_code not in (200, 201):
        print("  ❌ Ошибка на шаге 2")
        sys.exit(1)

    try:
        upload_result = r.json()
    except Exception as e:
        print(f"  ❌ Не JSON: {e}")
        sys.exit(1)

    # Извлекаем token
    if not upload_token:
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

    print(f"  → extracted token: {upload_token!r}")
    print()

    if not upload_token:
        print("  ❌ Нет token после загрузки")
        sys.exit(1)

    # ─── Шаг 3: POST /messages с вложением ───
    print("─── Шаг 3: POST /messages с вложением ───")
    try:
        attachments = [{
            "type": upload_type,
            "payload": {"token": upload_token},
        }]
        payload = {
            "text": "тест вложения",
            "attachments": attachments,
        }
        print(f"  Payload: {json.dumps(payload, ensure_ascii=False)[:500]}")
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
        print(f"  HTTP: {r.status_code}")
        print(f"  Body: {r.text[:500]}")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        sys.exit(1)

    if r.status_code != 200:
        print("  ❌ Ошибка на шаге 3")
        sys.exit(1)

    print()
    print("=" * 70)
    print("  ✅ ВСЁ ОК")
    print("=" * 70)


if __name__ == "__main__":
    main()