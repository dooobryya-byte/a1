#!/usr/bin/env python3
# setup_bot.py
"""
Настройка Hermes-сессий и БД для MAX-бота.

Меню:
1. Проверка наличия сессий Hermes (max_*****)
2. Создание / исправление сессий для чатов из config.py
3. Показать все сессии Hermes
4. Удаление сессий (интерактивный выбор чекбоксами)
5. Очистка БД бота (MessagesDB и MessagesRel)
0. Выход

Логика:
- Title сессии — это её имя. Hermes ищет `-c <title>` по точному совпадению.
- Если title не совпадает — скрипт переименовывает сессию.
- Если сессии нет — создаёт новую и переименовывает.
- Очистка БД удаляет все записи из messages и messages_rel (с бэкапом).
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
from db import DB_FILE


def clear_screen():
    """Очищает экран терминала."""
    os.system("cls" if os.name == "nt" else "clear")


def run_cmd(cmd_list, timeout=120):
    """Запускает команду и возвращает (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/home/a1",
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return None, f"Таймаут {timeout} сек", -1
    except FileNotFoundError:
        return None, f"Команда '{cmd_list[0]}' не найдена", -1
    except Exception as e:
        return None, str(e), -1


def get_sessions_raw():
    """Возвращает сырой вывод hermes sessions list."""
    out, err, code = run_cmd([HERMES_CMD, "sessions", "list"])
    if code != 0:
        return None, err or out
    return out, None


def parse_sessions(output):
    """Парсит вывод hermes sessions list."""
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
    """Ищет сессию по точному совпадению title."""
    for s in sessions:
        if s["title"] == title:
            return s
    return None


def find_similar_session(sessions, chat_id):
    """Ищет сессию, в title которой встречается chat_id."""
    for s in sessions:
        if chat_id in s["title"]:
            return s
    return None


# ==================== ПУНКТ 1 ====================

def check_sessions():
    """Пункт 1: Проверка наличия сессий для всех чатов."""
    print("\n" + "=" * 70)
    print("  ПРОВЕРКА СЕССИЙ HERMES")
    print("=" * 70)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Ошибка получения списка сессий: {err}")
        return

    sessions = parse_sessions(output)
    print(f"Всего сессий в Hermes: {len(sessions)}\n")

    print(f"{'Chat ID':<15} {'Имя':<25} {'Ожидаемый title':<20} {'Статус':<25}")
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
            ok_count += 1
        else:
            similar = find_similar_session(sessions, chat_id)
            if similar:
                status = "⚠️  Есть, но title другой"
                wrong_title.append((chat_id, name, similar))
            else:
                status = "❌ НЕТ"
                missing.append((chat_id, name))

        print(f"{chat_id:<15} {name:<25} {expected_title:<20} {status:<25}")

    print("-" * 90)
    print(f"✅ OK: {ok_count} / {len(ALLOWED_CHATS)}")

    if missing:
        print(f"\n❌ Отсутствуют сессии для:")
        for chat_id, name in missing:
            print(f"   · {name} ({chat_id}) — ожидается title 'max_{chat_id}'")

    if wrong_title:
        print(f"\n⚠️  Есть сессии, но title не совпадает:")
        for chat_id, name, s in wrong_title:
            print(f"   · {name} ({chat_id}):")
            print(f"     title: '{s['title']}' (ожидается 'max_{chat_id}')")
            print(f"     id:    {s['id']}")

    print("\n💡 Чтобы исправить — пункт 2 меню.")


# ==================== ПУНКТ 2 ====================

def create_or_fix_sessions():
    """Пункт 2: Создание или исправление сессий для всех чатов."""
    print("\n" + "=" * 70)
    print("  СОЗДАНИЕ / ИСПРАВЛЕНИЕ СЕССИЙ")
    print("=" * 70)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Не удалось получить текущий список сессий: {err}")
        return

    sessions = parse_sessions(output)

    for chat_id, info in ALLOWED_CHATS.items():
        name = info.get("name", chat_id)
        expected_title = f"max_{chat_id}"

        existing = find_session_by_title(sessions, expected_title)

        if existing:
            print(f"\n⏭  {name} ({chat_id}): сессия '{expected_title}' уже существует.")
            print(f"     id: {existing['id']}")
            continue

        similar = find_similar_session(sessions, chat_id)

        if similar:
            print(f"\n🔧 {name} ({chat_id}): найдена сессия с title '{similar['title']}'.")
            print(f"   Переименовываем в '{expected_title}'...")

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

        prompt = f"Привет, это начало сессии для {expected_title}"
        out, err, code = run_cmd([HERMES_CMD, "-z", prompt], timeout=180)

        if code != 0:
            print(f"   ❌ Ошибка создания сессии: {err or out}")
            continue

        print(f"   ✅ Сессия создана.")
        time.sleep(1)

        out, err, code = run_cmd([HERMES_CMD, "sessions", "list", "--limit", "1"])

        if code != 0:
            print(f"   ❌ Не удалось получить список сессий: {err}")
            continue

        new_sessions = parse_sessions(out)
        if not new_sessions:
            print(f"   ❌ Не удалось распознать ID новой сессии. Вывод:\n{out}")
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

    print("\n" + "=" * 70)
    print("✅ Готово.")


# ==================== ПУНКТ 3 ====================

def show_all_sessions():
    """Пункт 3: Показать все сессии Hermes."""
    print("\n" + "=" * 70)
    print("  ВСЕ СЕССИИ HERMES")
    print("=" * 70)

    out, err, code = run_cmd([HERMES_CMD, "sessions", "list"])
    if code != 0:
        print(f"❌ Ошибка: {err or out}")
        return

    print(out)


# ==================== ПУНКТ 4: УДАЛЕНИЕ СЕССИЙ ====================

def interactive_select(sessions):
    """Интерактивный выбор сессий чекбоксами."""
    if not sessions:
        print("Нет сессий для выбора.")
        return []

    selected = [False] * len(sessions)

    def render():
        clear_screen()
        print("=" * 90)
        print("  ИНТЕРАКТИВНЫЙ ВЫБОР СЕССИЙ")
        print("=" * 90)
        print("Команды:")
        print("  · номера через пробел (например: 1 3 5) — переключить выбор")
        print("  · all   — выбрать все")
        print("  · none  — снять все")
        print("  · done  — завершить выбор и перейти к удалению")
        print("  · q     — отмена (без удаления)")
        print("-" * 90)
        print(f"{'№':<4} {'Выбор':<7} {'Title':<35} {'Last Active':<15} {'ID':<25}")
        print("-" * 90)
        for i, s in enumerate(sessions, 1):
            mark = "[x]" if selected[i-1] else "[ ]"
            title = s["title"][:33] + (".." if len(s["title"]) > 33 else "")
            print(f"{i:<4} {mark:<7} {title:<35} {s['last_active']:<15} {s['id']:<25}")
        print("-" * 90)
        count = sum(selected)
        print(f"Выбрано: {count} / {len(sessions)}")

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
                print("⚠️  Неверный формат. Введите номера через пробел, all, none, done или q.")
                time.sleep(1.5)
                continue

            for n in nums:
                if 1 <= n <= len(sessions):
                    selected[n-1] = not selected[n-1]
                else:
                    print(f"⚠️  Номер {n} вне диапазона.")
                    time.sleep(1.5)

    result = [s for i, s in enumerate(sessions) if selected[i]]
    return result


def delete_sessions():
    """Пункт 4: Удаление сессий через интерактивный выбор."""
    print("\n" + "=" * 70)
    print("  УДАЛЕНИЕ СЕССИЙ")
    print("=" * 70)

    output, err = get_sessions_raw()
    if err:
        print(f"❌ Не удалось получить список сессий: {err}")
        return

    sessions = parse_sessions(output)
    if not sessions:
        print("Нет сессий для удаления.")
        return

    max_sessions = [s for s in sessions if s["title"].startswith("max_")]
    other_sessions = [s for s in sessions if not s["title"].startswith("max_")]

    if not max_sessions and not other_sessions:
        print("Нет сессий.")
        return

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

    print("\n" + "=" * 70)
    print(f"  БУДЕТ УДАЛЕНО: {len(selected)} сессий")
    print("=" * 70)
    for s in selected:
        print(f"  · {s['title']}  (id: {s['id']})")

    try:
        confirm = input("\nУдалить? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if confirm != "y":
        print("Отмена.")
        return

    print("\n" + "=" * 70)
    print("  УДАЛЕНИЕ...")
    print("=" * 70)

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
            print(f"  ❌ Ошибка удаления {s['title']} ({s['id']}): {err or out}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"✅ Удалено: {deleted}, ошибок: {failed}")
    print("=" * 70)


# ==================== ПУНКТ 5: ОЧИСТКА БД ====================

def clear_db():
    """Пункт 5: Очистка БД бота (MessagesDB и MessagesRel)."""
    print("\n" + "=" * 70)
    print("  ОЧИСТКА БД БОТА")
    print("=" * 70)

    if not os.path.exists(DB_FILE):
        print(f"❌ Файл БД не найден: {DB_FILE}")
        return

    # Показываем текущее состояние
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            total_rels = conn.execute("SELECT COUNT(*) FROM messages_rel").fetchone()[0]
        except sqlite3.OperationalError as e:
            print(f"❌ Ошибка чтения БД: {e}")
            return
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Ошибка открытия БД: {e}")
        return

    db_size = os.path.getsize(DB_FILE)
    print(f"\nФайл: {os.path.abspath(DB_FILE)}")
    print(f"Размер: {db_size} байт")
    print(f"\nТекущее содержимое:")
    print(f"  · messages:     {total_messages}")
    print(f"  · messages_rel: {total_rels}")

    if total_messages == 0 and total_rels == 0:
        print("\n✅ БД уже пуста.")
        return

    print("\nЧто очищать?")
    print("  1. Только messages_rel")
    print("  2. Только messages")
    print("  3. Всё (messages + messages_rel)")
    print("  0. Отмена")

    try:
        scope = input("Выберите: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if scope == "1":
        tables = ["messages_rel"]
    elif scope == "2":
        tables = ["messages"]
    elif scope == "3":
        tables = ["messages_rel", "messages"]
    elif scope == "0":
        print("Отмена.")
        return
    else:
        print("⚠️  Неверный выбор.")
        return

    # Запрос на бэкап
    try:
        want_backup = input("\nСделать бэкап перед очисткой? [Y/n]: ").strip().lower()
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

    # Подтверждение
    print(f"\nБудут очищены таблицы: {', '.join(tables)}")
    try:
        confirm = input("Продолжить? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтмена.")
        return

    if confirm != "y":
        print("Отмена.")
        return

    # Очистка
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            for table in tables:
                conn.execute(f"DELETE FROM {table}")
            # Сбрасываем автоинкремент для очищенных таблиц
            placeholders = ",".join("?" * len(tables))
            conn.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                tables,
            )
            conn.commit()
            # Сжимаем файл
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Ошибка очистки: {e}")
        return

    # Проверка результата
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            total_rels = conn.execute("SELECT COUNT(*) FROM messages_rel").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        pass

    new_size = os.path.getsize(DB_FILE)

    print("\n" + "=" * 70)
    print("✅ ОЧИСТКА ЗАВЕРШЕНА")
    print("=" * 70)
    print(f"messages:     {total_messages}")
    print(f"messages_rel: {total_rels}")
    print(f"Размер:       {db_size} → {new_size} байт")


# ==================== МЕНЮ ====================

def main_menu():
    while True:
        print("\n" + "=" * 50)
        print("  Setup Bot для MAX-бота")
        print("=" * 50)
        print("  1. Проверить наличие сессий (max_*)")
        print("  2. Создать / исправить отсутствующие сессии")
        print("  3. Показать все сессии Hermes")
        print("  4. Удалить сессии (интерактивный выбор)")
        print("  5. Очистить БД бота (MessagesDB и MessagesRel)")
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
            print("⚠️  Неверный выбор. Попробуйте снова.")


if __name__ == "__main__":
    if not ALLOWED_CHATS:
        print("❌ ALLOWED_CHATS пуст в config.py")
        sys.exit(1)

    if not HERMES_CMD:
        print("❌ HERMES_CMD не задан в config.py")
        sys.exit(1)

    main_menu()