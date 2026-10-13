#!/usr/bin/env python3
"""
hermes_session_model.py — показать/поменять модель у max_* сессий Hermes.

Использование:
    python hermes_session_model.py                           # показать
    python hermes_session_model.py --set apodex-1.1-mini:free  # поменять у всех
    python hermes_session_model.py --set apodex-1.1-mini:free --only max_8627605
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_sessions(conn, title_like="max_%"):
    cur = conn.execute("""
        SELECT id, title, model, billing_provider, last_activity_at
        FROM sessions
        WHERE title LIKE ?
        ORDER BY title
    """, (title_like,))
    return [dict(r) for r in cur.fetchall()]


def print_sessions(rows):
    if not rows:
        print("  (нет сессий)")
        return
    header = f"{'Title':<22} {'Model':<45} {'Provider':<10} {'Last Active':<20}"
    print(header)
    print("-" * len(header))
    for r in rows:
        last = r.get("last_activity_at")
        if last:
            last = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S")
        else:
            last = "—"
        print(
            f"{(r['title'] or '—'):<22} "
            f"{(r['model'] or '—'):<45} "
            f"{(r['billing_provider'] or '—'):<10} "
            f"{last:<20}"
        )


def set_model(conn, model, provider, only=None):
    if only:
        cur = conn.execute("""
            UPDATE sessions
            SET model = ?, billing_provider = ?
            WHERE title = ?
        """, (model, provider, only))
    else:
        cur = conn.execute("""
            UPDATE sessions
            SET model = ?, billing_provider = ?
            WHERE title LIKE 'max_%'
        """, (model, provider))
    conn.commit()
    return cur.rowcount


def main():
    p = argparse.ArgumentParser(description="Показать/поменять модель max_* сессий Hermes")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--set", dest="model", default=None)
    p.add_argument("--provider", default="custom")
    p.add_argument("--only", default=None)
    args = p.parse_args()

    if not os.path.exists(args.db):
        print(f"❌ Не найдено: {args.db}")
        sys.exit(1)

    conn = connect(args.db)

    if args.model:
        backup = f"{args.db}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.copy(args.db, backup)
        print(f"📦 Бэкап: {backup}")

        n = set_model(conn, args.model, args.provider, only=args.only)
        print(f"✏️  Обновлено сессий: {n}\n")

    print_sessions(list_sessions(conn))
    conn.close()


if __name__ == "__main__":
    main()