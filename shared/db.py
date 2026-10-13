# shared/db.py
import sqlite3
import threading
import os
from datetime import datetime

DB_PATH = os.environ.get("BOT_DB_PATH", "/home/a1/max-bot/state.db")

_lock = threading.RLock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL для одновременного доступа из bot.py и web
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    """Создаёт таблицы. Читает schema.sql."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        schema = f.read()

    with _lock:
        conn = _connect()
        conn.executescript(schema)
        conn.commit()
        conn.close()


def execute(query: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur


def fetchone(query: str, params: tuple = ()) -> dict | None:
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def fetchall(query: str, params: tuple = ()) -> list[dict]:
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"✅ БД инициализирована: {DB_PATH}")