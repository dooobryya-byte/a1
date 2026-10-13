# setup_bot.py
"""
Настройка Hermes-сессий и БД для MAX-бота.

Меню:
1. Проверка наличия сессий Hermes (max_*****) + модель LLM
2. Создание / исправление сессий для чатов из config.py
3. Показать все сессии Hermes + модель LLM
4. Удаление сессий (интерактивный выбор чекбоксами)
5. Очистка БД бота (messages, relations, chats, audit_log)
0. Выход
"""

import subprocess
import sys
import os
import time
import re
import shutil
import sqlite3
from datetime import datetime

from config import ALLOWED_CHATS, HERMES_CMD
from shared.db import DB_PATH as DB_FILE

HERMES_DB = os.path.expanduser("~/.hermes/state.db")
HERMES_CWD = "/home/a1"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def run_cmd(cmd_list, timeout=120):
    """Запускает команду и возвращает (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=HERMES_CWD,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return None, f"Таймаут {timeout} сек", -1
    except FileNotFoundError:
        return None, f"Команда '{cmd_list[0]}' не найдена", -1
    except Exception as e:
        return None, str(e), -1


# ==================== HERMES SESSIONS ====================

def get_sessions_raw():
    out, err, code = run_cmd([HERMES_CMD, "sessions", "list"])
    if code != 0:
        return None, err or out
    return out, None


def parse_sessions(output):
    sessions = []
    if not output:
        return sessions

    pattern = re.compile(
        r"^(?P<title>.+?)\s{2,}"
        r"(?P<workspace>\S+)\s{2,}"
        r"(?P<last_active>.+?)\s{2,}"
        r"(?P<id>\d{8}_\d{6}_[a-f0-9]+)\s*$"
    )

    for line in output.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("Title") or line.startswith("─") or line.startswith("…"):
            continue

        m = pattern.match(line)
        if not m:
            continue

        sessions.append({
            "title": m.group("title").strip(),
            "workspace": m.group("workspace").strip(),
            "last_active": m.group("last_active").strip(),
            "id": m.group("id").strip(),
        })

    return sessions


def find_session_by_title(sessions, title):
    for s in sessions:
        if s["title"] == title:
            return s
    return None


def find_similar_session(sessions, chat_id):
    """Ищет max_<chat_id> или max_<chat_id>_*."""
    pat = re.compile(rf"^max_{re.escape(str(chat_id))}(_|$)")
    for s in sessions:
        if pat.match(s["title"]):
            return s
    return None


# ==================== МОДЕЛИ LLM ИЗ БД HERMES ====================

def get_session_models() -> dict:
    """Возвращает {session_id: model} из БД Hermes."""
    if not os.path.exists(HERMES_DB):
        return {}

    try:
        conn = sqlite3.connect(HERMES_DB)
        conn.row_factory = sqlite3.Row
        # Пробуем взять 'model' из sessions
        rows = conn.execute(
            "SELECT id, model FROM sessions"
        ).fetchall()
        conn.close()
        return {row["id"]: (row["model"] or "—") for row in rows}
    except sqlite3.OperationalError as e:
        # Может, колонка называется иначе — попробуем узнать схему
        try:
            conn = sqlite3.connect(HERMES_DB)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
            conn.close()
            print(f"⚠️  В таблице sessions нет колонки 'model'. Колонки: {cols}")
        except Exception:
            pass
        return {}
    except Exception as e:
        print(f"⚠️  Ошибка чтения моделей: {e}")
        return {}


def short_model(model: str) -> str:
    """Сокращает имя модели для таблицы."""
    if not model or model == "—":
        return "—"
    # Убираем провайдера если есть "custom:openrouter"
    # Оставляем только имя модели
    m = model
    if ":" in m and "/" in m:
        # например: "custom:openrouter" → оставить как есть, но укоротить
        pass
    if len(m) > 28:
        return m[:26] + ".."
    return m


# ==================== ПУНКТ 1 ====================

def check_sessions():
    print("\n" + "=" * 90)
    print("  ПРОВЕРКА СЕССИЙ HERMES")
    print("=" * 90)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Ошибка получения списка сессий: {err}")
        return

    sessions = parse_sessions(output)
    models = get_session_models()
    print(f"Всего сессий в Hermes: {len(sessions)}\n")

    print(f"{'Chat ID':<15} {'Имя':<22} {'Модель LLM':<30} {'Статус':<20}")
    print("-" * 90)

    ok_count = 0
    missing = []
    wrong_title = []

    for chat_id, info in ALLOWED_CHATS.items():
        name = info.get("name", "—")
        expected_title = f"max_{chat_id}"

        found = find_session_by_title(sessions, expected_title)
        if found:
            status = "✅ OK"
            model = short_model(models.get(found["id"], "—"))
            ok_count += 1
        else:
            similar = find_similar_session(sessions, chat_id)
            if similar:
                status = "⚠️  title другой"
                model = short_model(models.get(similar["id"], "—"))
                wrong_title.append((chat_id, name, similar))
            else:
                status = "❌ НЕТ"
                model = "—"
                missing.append((chat_id, name))

        name_short = name[:20] + (".." if len(name) > 20 else "")
        print(f"{chat_id:<15} {name_short:<22} {model:<30} {status:<20}")

    print("-" * 90)
    print(f"✅ OK: {ok_count} / {len(ALLOWED_CHATS)}")

    if missing:
        print(f"\n❌ Отсутствуют сессии для:")
        for chat_id, name in missing:
            print(f"   · {name} ({chat_id}) — ожидается 'max_{chat_id}'")

    if wrong_title:
        print(f"\n⚠️  Есть сессии, но title не совпадает:")
        for chat_id, name, s in wrong_title:
            print(f"   · {name} ({chat_id}):")
            print(f"     title: '{s['title']}' (ожидается 'max_{chat_id}')")
            print(f"     id:    {s['id']}")
            print(f"     model: {models.get(s['id'], '—')}")

    print("\n💡 Чтобы исправить — пункт 2 меню.")


# ==================== ПУНКТ 2 ====================

def create_or_fix_sessions():
    print("\n" + "=" * 90)
    print("  СОЗДАНИЕ / ИСПРАВЛЕНИЕ СЕССИЙ")
    print("=" * 90)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Не удалось получить список сессий: {err}")
        return

    sessions = parse_sessions(output)

    for chat_id, info in ALLOWED_CHATS.items():
        name = info.get("name", chat_id)
        expected_title = f"max_{chat_id}"

        existing = find_session_by_title(sessions, expected_title)
        if existing:
            print(f"\n⏭  {name} ({chat_id}): '{expected_title}' уже существует.")
            print(f"     id: {existing['id']}")
            continue

        similar = find_similar_session(sessions, chat_id)
        if similar:
            print(f"\n🔧 {name} ({chat_id}): найдена '{similar['title']}', переименовываем...")
            out, err, code = run_cmd([
                HERMES_CMD, "sessions", "rename",
                similar["id"], expected_title,
            ])
            if code != 0:
                print(f"   ❌ Ошибка переименования: {err or out}")
                continue
            print(f"   ✅ Переименовано.")
            continue

        print(f"\n➡️  {name} ({chat_id}): сессия отсутствует, создаём...")

        # 1. Пробуем sessions new --title (без LLM)
        out, err, code = run_cmd([
            HERMES_CMD, "sessions", "new",
            "--title", expected_title,
        ], timeout=30)

        if code == 0:
            print(f"   ✅ Создана через 'sessions new'.")
            continue

        # 2. Fallback через -z (нужен рабочий LLM)
        print(f"   ⚠️  sessions new не сработал ({err or out})")
        print(f"   ⚠️  Пробую через -z (нужен рабочий LLM)...")

        prompt = f"Привет, это начало сессии для {expected_title}"
        out, err, code = run_cmd([HERMES_CMD, "-z", prompt], timeout=180)

        if code != 0:
            print(f"   ❌ Ошибка: {err or out}")
            print(f"   💡 Проверь /status — возможно, модель недоступна")
            continue

        time.sleep(1)
        out, err, code = run_cmd([HERMES_CMD, "sessions", "list", "--limit", "1"])
        if code != 0:
            print(f"   ❌ Не удалось получить список: {err}")
            continue

        new_sessions = parse_sessions(out)
        if not new_sessions:
            print(f"   ❌ Не удалось распознать ID. Вывод:\n{out}")
            continue

        new_id = new_sessions[0]["id"]
        print(f"   ID новой сессии: {new_id}")

        out, err, code = run_cmd([
            HERMES_CMD, "sessions", "rename",
            new_id, expected_title,
        ])
        if code != 0:
            print(f"   ❌ Ошибка переименования: {err or out}")
            continue

        print(f"   ✅ Переименовано в '{expected_title}'")

    print("\n" + "=" * 90)
    print("✅ Готово.")


# ==================== ПУНКТ 3 ====================

def show_all_sessions():
    print("\n" + "=" * 90)
    print("  ВСЕ СЕССИИ HERMES")
    print("=" * 90)

    out, err, code = run_cmd([HERMES_CMD, "sessions", "list"])
    if code != 0:
        print(f"❌ Ошибка: {err or out}")
        return

    # Вывод сырой команды
    print(out)

    # Дополнительно — таблица с моделями
    sessions = parse_sessions(out)
    models = get_session_models()

    if sessions:
        print("\n" + "─" * 90)
        print("  МОДЕЛИ LLM ПО СЕССИЯМ")
        print("─" * 90)
        print(f"{'Session ID':<28} {'Title':<30} {'Model':<30}")
        print("-" * 90)
        for s in sessions:
            title = s["title"][:28] + (".." if len(s["title"]) > 28 else "")
            model = short_model(models.get(s["id"], "—"))
            print(f"{s['id']:<28} {title:<30} {model:<30}")
        print("-" * 90)
        print(f"Всего: {len(sessions)}")
    else:
        print("\n⚠️  Не удалось распарсить сессии для таблицы моделей.")


# ==================== ПУНКТ 4 ====================

def interactive_select(sessions):
    if not sessions:
        print("Нет сессий для выбора.")
        return []

    selected = [False] * len(sessions)
    models = get_session_models()

    def render():
        clear_screen()
        print("=" * 100)
        print("  ИНТЕРАКТИВНЫЙ ВЫБОР СЕССИЙ")
        print("=" * 100)
        print("Команды:")
        print("  · номера через пробел (например: 1 3 5) — переключить выбор")
        print("  · all   — выбрать все")
        print("  · none  — снять все")
        print("  · done  — завершить выбор")
        print("  · q     — отмена")
        print("-" * 100)
        print(f"{'№':<4} {'Выбор':<7} {'Title':<30} {'Модель':<28} {'Last Active':<15} {'ID':<22}")
        print("-" * 100)
        for i, s in enumerate(sessions, 1):
            mark = "[x]" if selected[i-1] else "[ ]"
            title = s["title"][:28] + (".." if len(s["title"]) > 28 else "")
            model = short_model(models.get(s["id"], "—"))
            print(f"{i:<4} {mark:<7} {title:<30} {model:<28} {s['last_active']:<15} {s['id']:<22}")
        print("-" * 100)
        print(f"Выбрано: {sum(selected)} / {len(sessions)}")

    while True:
        render()
        try:
            choice = input("\nКоманда или номера: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nОтмена.")
            return []

        if choice in ("done", "d"):
            break
        elif choice in ("q", "quit", "exit", "cancel"):
            print("Отмена.")
            return []
        elif choice == "all":
            selected = [True] * len(sessions)
        elif choice == "none":
            selected = [False] * len(sessions)
        else:
            try:
                nums = [int(x) for x in choice.split()]
            except ValueError:
                print("⚠️  Неверный формат.")
                time.sleep(1.5)
                continue

            for n in nums:
                if 1 <= n <= len(sessions):
                    selected[n-1] = not selected[n-1]
                else:
                    print(f"⚠️  Номер {n} вне диапазона.")
                    time.sleep(1.5)

    return [s for i, s in enumerate(sessions) if selected[i]]


def delete_sessions():
    print("\n" + "=" * 90)
    print("  УДАЛЕНИЕ СЕССИЙ")
    print("=" * 90)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Не удалось получить список: {err}")
        return

    sessions = parse_sessions(output)
    if not sessions:
        print("Нет сессий для удаления.")
        return

    max_sessions = [s for s in sessions if s["title"].startswith("max_")]
    other_sessions = [s for s in sessions if not s["title"].startswith("max_")]

    print(f"\nВсего сессий: {len(sessions)}")
    print(f"  · max_* сессий: {len(max_sessions)}")
    print(f"  · остальных:    {len(other_sessions)}")

    print("\nЧто удалять?")
    print("  1. Только max_* сессии")
    print("  2. Только остальные")
    print("  3. Все сессии")
    print("  0. Отмена")

    try:
        scope = input("Выберите: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if scope == "1":
        to_choose = max_sessions
    elif scope == "2":
        to_choose = other_sessions
    elif scope == "3":
        to_choose = sessions
    elif scope == "0":
        print("Отмена.")
        return
    else:
        print("⚠️  Неверный выбор.")
        return

    if not to_choose:
        print("Нет сессий в выбранной категории.")
        return

    selected = interactive_select(to_choose)
    if not selected:
        print("\nНичего не выбрано.")
        return

    print("\n" + "=" * 90)
    print(f"  БУДЕТ УДАЛЕНО: {len(selected)} сессий")
    print("=" * 90)
    models = get_session_models()
    for s in selected:
        print(f"  · {s['title']}  (id: {s['id']}, model: {models.get(s['id'], '—')})")

    try:
        confirm = input("\nУдалить? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if confirm != "y":
        print("Отмена.")
        return

    print("\n" + "=" * 90)
    print("  УДАЛЕНИЕ...")
    print("=" * 90)

    deleted = 0
    failed = 0
    for s in selected:
        out, err, code = run_cmd([
            HERMES_CMD, "sessions", "delete", s["id"], "--yes"
        ])
        if code == 0:
            print(f"  ✅ Удалена: {s['title']} ({s['id']})")
            deleted += 1
        else:
            print(f"  ❌ Ошибка: {s['title']} ({s['id']}): {err or out}")
            failed += 1

    print("\n" + "=" * 90)
    print(f"✅ Удалено: {deleted}, ошибок: {failed}")
    print("=" * 90)


# ==================== ПУНКТ 5: ОЧИСТКА БД ====================

def _table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _count(conn, table):
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return None


def clear_db():
    print("\n" + "=" * 90)
    print("  ОЧИСТКА БД БОТА")
    print("=" * 90)

    if not os.path.exists(DB_FILE):
        print(f"❌ Файл БД не найден: {DB_FILE}")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
    except Exception as e:
        print(f"❌ Ошибка открытия БД: {e}")
        return

    TABLES = ["messages", "relations", "chats", "audit_log"]

    try:
        present = [t for t in TABLES if _table_exists(conn, t)]
        if not present:
            print("⚠️  В БД нет ни одной ожидаемой таблицы.")
            try:
                tables = [
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall()
                ]
                if tables:
                    print(f"    Таблицы: {', '.join(tables)}")
            except Exception:
                pass
            return

        counts = {t: _count(conn, t) for t in present}
    finally:
        conn.close()

    db_size = os.path.getsize(DB_FILE)
    print(f"\nФайл: {os.path.abspath(DB_FILE)}")
    print(f"Размер: {db_size} байт")
    print(f"\nТекущее содержимое:")
    for t in present:
        print(f"  · {t}: {counts[t]}")

    if all((counts.get(t) or 0) == 0 for t in present):
        print("\n✅ Все таблицы уже пусты.")
        return

    print("\nЧто очищать?")
    for i, t in enumerate(present, 1):
        print(f"  {i}. Только {t}")
    print(f"  {len(present) + 1}. Всё ({', '.join(present)})")
    print("  0. Отмена")

    try:
        scope = input("Выберите: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if scope == "0":
        print("Отмена.")
        return

    try:
        n = int(scope)
    except ValueError:
        print("⚠️  Неверный выбор.")
        return

    if n == len(present) + 1:
        tables_to_clear = present
    elif 1 <= n <= len(present):
        tables_to_clear = [present[n - 1]]
    else:
        print("⚠️  Неверный выбор.")
        return

    try:
        want_backup = input("\nБэкап перед очисткой? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if want_backup != "n":
        backup_file = f"{DB_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy(DB_FILE, backup_file)
            print(f"📦 Бэкап: {backup_file}")
        except Exception as e:
            print(f"❌ Ошибка бэкапа: {e}")
            return

    print(f"\nБудут очищены: {', '.join(tables_to_clear)}")
    try:
        confirm = input("Продолжить? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if confirm != "y":
        print("Отмена.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            order = []
            for t in ["relations", "messages", "chats", "audit_log"]:
                if t in tables_to_clear:
                    order.append(t)
            for t in order:
                conn.execute(f"DELETE FROM {t}")
            placeholders = ",".join("?" * len(order))
            conn.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                order,
            )
            conn.commit()
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Ошибка очистки: {e}")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            counts = {t: _count(conn, t) for t in tables_to_clear}
        finally:
            conn.close()
    except Exception:
        counts = {}

    new_size = os.path.getsize(DB_FILE)

    print("\n" + "=" * 90)
    print("✅ ОЧИСТКА ЗАВЕРШЕНА")
    print("=" * 90)
    for t, c in counts.items():
        print(f"{t}: {c}")
    print(f"Размер: {db_size} → {new_size} байт")


# ==================== МЕНЮ ====================

def main_menu():
    while True:
        print("\n" + "=" * 50)
        print("  Setup Bot для MAX-бота")
        print("=" * 50)
        print("  1. Проверить сессии (max_*) + модель LLM")
        print("  2. Создать / исправить сессии")
        print("  3. Показать все сессии + модели LLM")
        print("  4. Удалить сессии (интерактивный выбор)")
        print("  5. Очистить БД бота")
        print("  0. Выход")
        print("-" * 50)

        try:
            choice = input("Выберите пункт: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nВыход.")
            break

        if choice == "1":
            check_sessions()
        elif choice == "2":
            create_or_fix_sessions()
        elif choice == "3":
            show_all_sessions()
        elif choice == "4":
            delete_sessions()
        elif choice == "5":
            clear_db()
        elif choice == "0":
            print("Выход.")
            break
        else:
            print("⚠️  Неверный выбор.")


if __name__ == "__main__":
    if not ALLOWED_CHATS:
        print("❌ ALLOWED_CHATS пуст в config.py")
        sys.exit(1)

    if not HERMES_CMD:
        print("❌ HERMES_CMD не задан в config.py")
        sys.exit(1)

    main_menu()