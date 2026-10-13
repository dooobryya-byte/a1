#!/usr/bin/env python3
# chat_messages.py — просмотр сообщений через MAX Bot API.
#
# Использование:
#   python chat_messages.py                    # интерактивное меню (CLI)
#   python chat_messages.py 8627605            # конкретный чат
#   python chat_messages.py --all              # все чаты (текст)
#   python chat_messages.py --all --html-all   # HTML все чаты (sidebar)
#   python chat_messages.py 8627605 --html     # HTML один чат
#   python chat_messages.py --chat-id 12345
#   python chat_messages.py --message-ids "mid.x,mid.y"
#   python chat_messages.py --from-db 8627605
#   python chat_messages.py 8627605 --count 30 --since 24h --json

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

from config import MAX_BOT_TOKEN, MAX_API_BASE, ALLOWED_CHATS
import db


# ==================== API ====================

def api_get(path: str, params: dict = None, timeout=15) -> dict:
    url = f"{MAX_API_BASE}{path}"
    headers = {"Authorization": MAX_BOT_TOKEN}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            print(f"⚠ HTTP {r.status_code}: {r.text[:300]}")
            return {}
        return r.json()
    except requests.RequestException as e:
        print(f"⚠ Ошибка: {type(e).__name__}: {e}")
        return {}


# ==================== Форматирование ====================

def format_ts(ts_ms: int) -> str:
    if not ts_ms:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def format_ts_short(ts_ms: int) -> str:
    if not ts_ms:
        return ""
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%d.%m %H:%M")


def format_message(msg: dict, index: int = 0) -> str:
    body = msg.get("body") or {}
    sender = msg.get("sender") or {}
    recipient = msg.get("recipient") or {}

    mid = body.get("mid", "—")
    text = (body.get("text") or "").replace("\n", " ")[:120]
    sender_name = sender.get("name") or sender.get("first_name") or "—"
    sender_id = sender.get("user_id", "—")
    is_bot = sender.get("is_bot", False)
    ts_str = format_ts(msg.get("timestamp", 0))
    chat_id = recipient.get("chat_id", "—")

    sender_tag = f"{sender_name} ({sender_id})"
    if is_bot:
        sender_tag += " 🤖"

    return (
        f"[{index:>3}] {ts_str}  chat_id={chat_id}\n"
        f"      {sender_tag}\n"
        f"      mid: {mid}\n"
        f"      {text}"
    )


def print_messages(messages: list, label: str = ""):
    if not messages:
        print("  (нет сообщений)")
        return

    print(f"\n{'=' * 100}")
    print(f"  {label} — {len(messages)} сообщений")
    print(f"{'=' * 100}\n")

    for i, msg in enumerate(messages, 1):
        print(format_message(msg, i))
        print()


# ==================== Логика ====================

def parse_since(since: str) -> int | None:
    if not since:
        return None
    if since.endswith("h"):
        h = int(since[:-1])
        return int((datetime.now() - timedelta(hours=h)).timestamp() * 1000)
    if since.endswith("d"):
        d = int(since[:-1])
        return int((datetime.now() - timedelta(days=d)).timestamp() * 1000)
    if since.isdigit():
        return int(since)
    return None


def fetch_messages(chat_id: int = None, message_ids: str = None,
                   count: int = 50, to_ms: int = None) -> list:
    params = {}
    if chat_id is not None:
        params["chat_id"] = chat_id
    elif message_ids:
        params["message_ids"] = message_ids
    else:
        return []

    params["count"] = min(max(count, 1), 100)
    if to_ms:
        params["to"] = to_ms

    data = api_get("/messages", params=params)
    return data.get("messages", [])


def get_chat_id_for_user(user_id: str) -> int | None:
    info = ALLOWED_CHATS.get(str(user_id), {})
    return info.get("chat_id")


# ==================== HTML (sidebar) ====================

def _html_escape(s: str) -> str:
    if not s:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _initials(name: str) -> str:
    if not name:
        return "?"
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def message_to_html(msg: dict) -> str:
    body = msg.get("body") or {}
    sender = msg.get("sender") or {}

    mid = body.get("mid", "")
    text = body.get("text", "")
    sender_name = sender.get("name") or sender.get("first_name") or "—"
    is_bot = sender.get("is_bot", False)
    ts = msg.get("timestamp", 0)
    ts_str = format_ts(ts)
    ts_short = format_ts_short(ts)

    cls = "bot" if is_bot else "user"

    return (
        f'<div class="msg {cls}">\n'
        f'  <div class="bubble">\n'
        f'    <div class="sender">{_html_escape(sender_name)}'
        f'{" 🤖" if is_bot else ""}</div>\n'
        f'    <div class="text">{_html_escape(text)}</div>\n'
        f'    <div class="footer">\n'
        f'      <span class="time" title="{ts_str}">{ts_short}</span>\n'
        f'      <span class="mid" title="{_html_escape(mid)}" '
        f'onclick="copyMid(this)" data-mid="{_html_escape(mid)}">'
        f'{_html_escape(mid)}</span>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'</div>'
    )


def generate_sidebar_html(chats_data: list[dict]) -> str:
    """
    chats_data: список dict с полями:
      user_id, name, city, chat_id, messages (list), error (опц.)
    """
    # Sidebar
    sidebar_items = []
    for i, c in enumerate(chats_data):
        uid = c["user_id"]
        name = c["name"]
        city = c.get("city", "")
        count = len(c.get("messages") or [])
        active = "active" if i == 0 else ""
        initials = _initials(name)

        sidebar_items.append(
            f'<div class="chat-item {active}" data-chat="chat-{uid}" '
            f'onclick="showChat(\'chat-{uid}\', this)">'
            f'  <div class="avatar">{_html_escape(initials)}</div>'
            f'  <div class="chat-info">'
            f'    <div class="chat-name">{_html_escape(name)}</div>'
            f'    <div class="chat-meta">{_html_escape(city)} · {count} сообщ.</div>'
            f'  </div>'
            f'</div>'
        )

    # Content
    content_blocks = []
    for i, c in enumerate(chats_data):
        uid = c["user_id"]
        name = c["name"]
        chat_id = c.get("chat_id")
        error = c.get("error")
        messages = c.get("messages") or []
        active = "active" if i == 0 else ""

        if error:
            body_html = f'<div class="empty">⚠ {_html_escape(error)}</div>'
        elif not messages:
            body_html = '<div class="empty">Нет сообщений</div>'
        else:
            sorted_msgs = sorted(messages, key=lambda m: m.get("timestamp", 0))
            body_html = "\n".join(message_to_html(m) for m in sorted_msgs)

        content_blocks.append(
            f'<div class="chat-content {active}" id="chat-{uid}">'
            f'  <div class="content-header">'
            f'    <div class="content-name">{_html_escape(name)}</div>'
            f'    <div class="content-meta">'
            f'user_id={_html_escape(uid)} · chat_id={_html_escape(chat_id)} · '
            f'{len(messages)} сообщений'
            f'    </div>'
            f'  </div>'
            f'  <div class="content-body">'
            f'    {body_html}'
            f'  </div>'
            f'</div>'
        )

    sidebar_html = "\n".join(sidebar_items)
    content_html = "\n".join(content_blocks)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>📬 MAX Bot — просмотр чатов</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    height: 100%;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0e1621;
    color: #e0e0e0;
  }}
  .layout {{
    display: flex;
    height: 100vh;
    overflow: hidden;
  }}

  /* ─── Sidebar ─── */
  .sidebar {{
    width: 320px;
    min-width: 320px;
    background: #17212b;
    border-right: 1px solid #0a0e14;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }}
  .sidebar-header {{
    padding: 16px;
    border-bottom: 1px solid #0a0e14;
    font-size: 16px;
    font-weight: 600;
    color: #ffffff;
    position: sticky;
    top: 0;
    background: #17212b;
    z-index: 1;
  }}
  .chat-item {{
    display: flex;
    align-items: center;
    padding: 12px 16px;
    cursor: pointer;
    border-bottom: 1px solid #0a0e14;
    transition: background 0.15s;
  }}
  .chat-item:hover {{
    background: #202b36;
  }}
  .chat-item.active {{
    background: #2b5278;
  }}
  .avatar {{
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: #5288c1;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 16px;
    flex-shrink: 0;
    margin-right: 12px;
  }}
  .chat-item.active .avatar {{
    background: #ffffff;
    color: #2b5278;
  }}
  .chat-info {{
    flex: 1;
    min-width: 0;
  }}
  .chat-name {{
    font-size: 14px;
    font-weight: 600;
    color: #ffffff;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .chat-meta {{
    font-size: 12px;
    color: #7d8b99;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .chat-item.active .chat-meta {{
    color: #c8d9e8;
  }}

  /* ─── Content ─── */
  .content {{
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #0e1621;
  }}
  .chat-content {{
    display: none;
    flex-direction: column;
    height: 100%;
  }}
  .chat-content.active {{
    display: flex;
  }}
  .content-header {{
    padding: 16px 24px;
    border-bottom: 1px solid #0a0e14;
    background: #17212b;
    flex-shrink: 0;
  }}
  .content-name {{
    font-size: 16px;
    font-weight: 600;
    color: #ffffff;
  }}
  .content-meta {{
    font-size: 12px;
    color: #7d8b99;
    margin-top: 4px;
    font-family: monospace;
  }}
  .content-body {{
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
  }}
  .msg {{
    display: flex;
    margin-bottom: 12px;
  }}
  .msg.bot {{
    justify-content: flex-start;
  }}
  .msg.user {{
    justify-content: flex-end;
  }}
  .bubble {{
    max-width: 65%;
    padding: 8px 12px;
    border-radius: 12px;
    word-wrap: break-word;
    white-space: pre-wrap;
    line-height: 1.4;
  }}
  .msg.bot .bubble {{
    background: #182533;
    color: #e0e0e0;
    border-bottom-left-radius: 3px;
  }}
  .msg.user .bubble {{
    background: #2b5278;
    color: #ffffff;
    border-bottom-right-radius: 3px;
  }}
  .bubble .sender {{
    font-size: 11px;
    font-weight: 600;
    color: #5288c1;
    margin-bottom: 3px;
  }}
  .msg.user .bubble .sender {{
    color: #a8c8e8;
  }}
  .bubble .text {{
    font-size: 14px;
  }}
  .bubble .footer {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 4px;
    font-size: 10px;
    color: #7d8b99;
  }}
  .msg.user .bubble .footer {{
    color: #a8c8e8;
  }}
  .bubble .time {{
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .bubble .mid {{
    font-family: monospace;
    font-size: 9px;
    color: #5a6a78;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px;
    direction: rtl;
    text-align: left;
    cursor: pointer;
    transition: color 0.15s;
  }}
  .bubble .mid:hover {{
    color: #7d8b99;
  }}
  .msg.user .bubble .mid {{
    color: #8aa8c8;
  }}
  .msg.user .bubble .mid:hover {{
    color: #c8d9e8;
  }}
  .empty {{
    text-align: center;
    color: #7d8b99;
    padding: 40px;
    font-size: 14px;
  }}

  /* ─── Toast для copy ─── */
  .toast {{
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    background: #2b5278;
    color: #ffffff;
    padding: 10px 20px;
    border-radius: 6px;
    font-size: 13px;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.3s;
    z-index: 100;
  }}
  .toast.show {{
    opacity: 1;
  }}

  /* ─── Scrollbar ─── */
  ::-webkit-scrollbar {{
    width: 8px;
  }}
  ::-webkit-scrollbar-track {{
    background: transparent;
  }}
  ::-webkit-scrollbar-thumb {{
    background: #2b3a48;
    border-radius: 4px;
  }}
  ::-webkit-scrollbar-thumb:hover {{
    background: #3a4a58;
  }}
</style>
</head>
<body>
<div class="layout">
  <div class="sidebar">
    <div class="sidebar-header">📬 Чаты ({len(chats_data)})</div>
    {sidebar_html}
  </div>
  <div class="content">
    {content_html}
  </div>
</div>
<div class="toast" id="toast">Скопировано</div>

<script>
function showChat(chatId, el) {{
  document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
  document.querySelectorAll('.chat-content').forEach(c => c.classList.remove('active'));

  el.classList.add('active');
  const content = document.getElementById(chatId);
  if (content) {{
    content.classList.add('active');
    const body = content.querySelector('.content-body');
    if (body) body.scrollTop = body.scrollHeight;
  }}
}}

function copyMid(el) {{
  const mid = el.getAttribute('data-mid');
  if (!mid) return;

  navigator.clipboard.writeText(mid).then(() => {{
    const toast = document.getElementById('toast');
    toast.textContent = '📋 Скопировано: ' + mid;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1500);
  }}).catch(err => {{
    console.error('Copy failed:', err);
    // Fallback для file:// (некоторые браузеры блокируют clipboard)
    const ta = document.createElement('textarea');
    ta.value = mid;
    document.body.appendChild(ta);
    ta.select();
    try {{
      document.execCommand('copy');
      const toast = document.getElementById('toast');
      toast.textContent = '📋 Скопировано: ' + mid;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 1500);
    }} catch (e) {{
      console.error(e);
    }}
    document.body.removeChild(ta);
  }});
}}

// При загрузке — скролл вниз активного чата
window.addEventListener('load', () => {{
  const active = document.querySelector('.chat-content.active .content-body');
  if (active) active.scrollTop = active.scrollHeight;
}});
</script>
</body>
</html>
"""


def save_html(html: str, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML сохранён: {path}")
    print(f"   Открой: file://{os.path.abspath(path)}")


# ==================== Режимы ====================

def run_one_chat(user_id: str, info: dict, args):
    name = info.get("name", "—")
    chat_id = info.get("chat_id")

    print(f"\n{'─' * 90}")
    print(f"  📬 {name} (user_id={user_id}, chat_id={chat_id})")
    print(f"{'─' * 90}\n")

    if not chat_id:
        print(f"  ❌ У чата не задан chat_id в config.py")
        return

    to_ms = parse_since(args.since)
    messages = fetch_messages(chat_id=chat_id, count=args.count, to_ms=to_ms)

    if args.html is not None:
        chats_data = [{
            "user_id": user_id,
            "name": name,
            "city": info.get("city", ""),
            "chat_id": chat_id,
            "messages": messages,
        }]
        html = generate_sidebar_html(chats_data)
        out_path = args.html if isinstance(args.html, str) else f"/tmp/chat_{user_id}.html"
        save_html(html, out_path)
        return

    if args.json:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
    else:
        print_messages(messages, f"{name} (chat_id={chat_id})")


def run_all_chats(args):
    to_ms = parse_since(args.since)

    if args.html_all is not None:
        chats_data = []
        for user_id, info in ALLOWED_CHATS.items():
            name = info.get("name", "—")
            chat_id = info.get("chat_id")
            if not chat_id:
                chats_data.append({
                    "user_id": user_id,
                    "name": name,
                    "city": info.get("city", ""),
                    "chat_id": None,
                    "messages": [],
                    "error": "chat_id не задан в config.py",
                })
                continue

            messages = fetch_messages(chat_id=chat_id, count=args.count, to_ms=to_ms)
            chats_data.append({
                "user_id": user_id,
                "name": name,
                "city": info.get("city", ""),
                "chat_id": chat_id,
                "messages": messages,
            })

        html = generate_sidebar_html(chats_data)
        out_path = args.html_all if isinstance(args.html_all, str) else "/tmp/all_chats.html"
        save_html(html, out_path)
        return

    print(f"\nЗапрашиваю для {len(ALLOWED_CHATS)} чатов...\n")
    for user_id, info in ALLOWED_CHATS.items():
        name = info.get("name", "—")
        chat_id = info.get("chat_id")
        print(f"\n{'━' * 100}")
        print(f"  {name} (user_id={user_id})")
        print(f"{'━' * 100}")
        if not chat_id:
            print(f"  ⏭ chat_id не задан — пропускаю")
            continue
        messages = fetch_messages(chat_id=chat_id, count=args.count, to_ms=to_ms)
        if args.json:
            print(json.dumps(messages, indent=2, ensure_ascii=False))
        else:
            print_messages(messages, f"{name} (chat_id={chat_id})")


def run_from_db(user_id: str, args):
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    rows = db.get_messages_since(user_id, today_start)

    if not rows:
        print(f"  ❌ Нет сообщений для {user_id} за сегодня в БД")
        return

    mids = [r["id_message"] for r in rows if r["id_message"]]
    print(f"  Найдено {len(mids)} mid в БД")
    print(f"  Запрашиваю через GET /messages...\n")

    messages = fetch_messages(message_ids=",".join(mids), count=args.count)

    if args.json:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
    else:
        print_messages(messages, f"user_id={user_id} (from DB)")


def run_message_ids(mids: str, args):
    messages = fetch_messages(message_ids=mids, count=args.count)
    if args.json:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
    else:
        print_messages(messages, f"message_ids={mids[:60]}...")


def run_chat_id(chat_id: int, args):
    to_ms = parse_since(args.since)
    messages = fetch_messages(chat_id=chat_id, count=args.count, to_ms=to_ms)

    if args.html is not None:
        chats_data = [{
            "user_id": str(chat_id),
            "name": f"chat_id={chat_id}",
            "city": "",
            "chat_id": chat_id,
            "messages": messages,
        }]
        html = generate_sidebar_html(chats_data)
        out_path = args.html if isinstance(args.html, str) else f"/tmp/chat_{chat_id}.html"
        save_html(html, out_path)
        return

    if args.json:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
    else:
        print_messages(messages, f"chat_id={chat_id}")


# ==================== Интерактивное меню ====================

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def interactive_menu(args) -> int:
    chats = list(ALLOWED_CHATS.items())

    while True:
        clear_screen()
        print("=" * 90)
        print("  📬 ПРОСМОТР СООБЩЕНИЙ MAX")
        print("=" * 90)
        print()
        print(f"  {'№':<4} {'user_id':<14} {'Name':<22} {'chat_id':<14} {'Город':<20}")
        print("  " + "-" * 84)

        for i, (uid, info) in enumerate(chats, 1):
            name = info.get("name", "—")
            cid = info.get("chat_id")
            cid_str = str(cid) if cid else "—"
            city = info.get("city", "—")
            print(f"  {i:<4} {uid:<14} {name[:20]:<22} {cid_str:<14} {city[:18]:<20}")

        print()
        print("  " + "─" * 45)
        print("  h  — HTML для всех чатов (sidebar)")
        print("  a  — все чаты (текст)")
        print("  d  — из БД (по mid)")
        print("  m  — ввести mid вручную")
        print("  c  — ввести chat_id вручную")
        print("  q  — выход")
        print()

        try:
            choice = input("  Выбор: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Отмена.")
            return 0

        if choice in ("q", "quit", "exit"):
            print("  Выход.")
            return 0

        if choice == "h":
            args.html_all = True
            run_all_chats(args)
            args.html_all = None
            input("\n  Нажми Enter...")
            continue

        if choice == "a":
            run_all_chats(args)
            input("\n  Нажми Enter для возврата в меню...")
            continue

        if choice == "d":
            uid = input("  user_id для БД: ").strip()
            if uid:
                run_from_db(uid, args)
                input("\n  Нажми Enter...")
            continue

        if choice == "m":
            mids = input("  mid через запятую: ").strip()
            if mids:
                run_message_ids(mids, args)
                input("\n  Нажми Enter...")
            continue

        if choice == "c":
            cid = input("  chat_id: ").strip()
            if cid.isdigit():
                run_chat_id(int(cid), args)
                input("\n  Нажми Enter...")
            continue

        try:
            n = int(choice)
            if 1 <= n <= len(chats):
                uid, info = chats[n - 1]
                mode = input("  Формат [t]екст / [h]tml? (Enter=текст): ").strip().lower()
                if mode == "h":
                    args.html = True
                    run_one_chat(uid, info, args)
                    args.html = None
                else:
                    run_one_chat(uid, info, args)
                input("\n  Нажми Enter для возврата в меню...")
                continue
            else:
                print(f"  ⚠ Номер {n} вне диапазона")
        except ValueError:
            print(f"  ⚠ Неверный ввод: {choice!r}")

        time.sleep(1)


# ==================== main ====================

def main():
    p = argparse.ArgumentParser(description="Просмотр сообщений через MAX Bot API")
    p.add_argument("user_id", nargs="?", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--chat-id", type=int, default=None)
    p.add_argument("--message-ids", default=None)
    p.add_argument("--from-db", default=None)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--since", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--html", nargs="?", const=True, default=None,
                   help="HTML для одного чата (путь опционально)")
    p.add_argument("--html-all", nargs="?", const=True, default=None,
                   help="HTML для всех чатов с sidebar (путь опционально)")
    args = p.parse_args()

    if args.message_ids:
        run_message_ids(args.message_ids, args)
        return 0

    if args.from_db:
        run_from_db(args.from_db, args)
        return 0

    if args.chat_id and not args.user_id and not args.all:
        run_chat_id(args.chat_id, args)
        return 0

    if args.all or args.html_all is not None:
        run_all_chats(args)
        return 0

    if args.user_id:
        if args.user_id not in ALLOWED_CHATS:
            print(f"❌ user_id={args.user_id} нет в ALLOWED_CHATS")
            print(f"   Доступные: {list(ALLOWED_CHATS.keys())}")
            return 1
        info = ALLOWED_CHATS[args.user_id]
        run_one_chat(args.user_id, info, args)
        return 0

    return interactive_menu(args)


if __name__ == "__main__":
    sys.exit(main())