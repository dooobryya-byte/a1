# send_aphorism.py
import random
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from config import BASE, API_TOKEN, ALLOWED_CHATS


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def build_url(date=None):
    """URL страницы афоризмов на дату. По умолчанию — сегодня."""
    if date is None:
        date = datetime.now()
    # формат: aYYMMDD.html, например a261004.html
    return f"https://www.anekdot.ru/an/an{date.strftime('%y%m')}/a{date.strftime('%y%m%d')}.html"


def fetch_aphorisms(url):
    """Скачивает страницу и вытаскивает список афоризмов."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"[{now_str()}] ⚠ HTTP {resp.status_code} для {url}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    aphorisms = []

    # Афоризмы на anekdot.ru лежат в блоках div.topicbox.
    for block in soup.select("div.topicbox"):
        text_div = block.select_one("div.text")
        if not text_div:
            continue

        for tag in text_div.select("a, script, style"):
            tag.decompose()

        text = text_div.get_text(separator="\n", strip=True)

        # Чистим: убираем строки типа "+47", "-3", "Обсудить", "Поделиться"
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if re.fullmatch(r"[+\-–]?\d+", line):
                continue
            if line in ("Обсудить", "Поделиться", "Ссылка", "Послать донат автору/рассказчику"):
                continue
            lines.append(line)

        clean = " ".join(lines).strip()

        # Отсеиваем слишком короткие / длинные
        if 15 <= len(clean) <= 500:
            aphorisms.append(clean)

    return aphorisms


def get_aphorism():
    """
    Возвращает один случайный афоризм с anekdot.ru за сегодня.
    Если страницы за сегодня нет — пробует вчера (до 7 дней назад).
    Если не удалось — возвращает None.
    """
    for delta in range(0, 7):
        date = datetime.now() - timedelta(days=delta)
        url = build_url(date)
        try:
            aphorisms = fetch_aphorisms(url)
        except Exception as e:
            print(f"[{now_str()}] ⚠ fetch_aphorisms error ({url}): {e}")
            continue

        if aphorisms:
            if delta > 0:
                print(f"[{now_str()}] 📖 афоризм с {date.strftime('%d.%m.%Y')}")
            return random.choice(aphorisms)

    print(f"[{now_str()}] ⚠ Не удалось получить афоризм за 7 дней")
    return None


def send(chat_id, text):
    """Отправляет сообщение в чат MAX."""
    url = f"{BASE}/sendMessage/{API_TOKEN}"
    try:
        resp = requests.post(
            url,
            json={"chatId": chat_id, "message": text},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def main():
    url = build_url()
    print(f"[{now_str()}] 🌐 Афоризмы с {url}")

    aphorisms = fetch_aphorisms(url)
    if not aphorisms:
        print(f"[{now_str()}] ⚠ Не удалось получить афоризмы — выходим")
        return

    print(f"[{now_str()}] 📚 Найдено афоризмов: {len(aphorisms)}")

    for chat_id, info in ALLOWED_CHATS.items():
        name = info["name"]
        aphorism = random.choice(aphorisms)
        text = f"📌 Афоризм дня:\n\n{aphorism}"

        if send(chat_id, text):
            print(f"[{now_str()}] 💬 отправлен {chat_id} ({name}): "
                  f"{aphorism[:50]}...")
        else:
            print(f"[{now_str()}] ⚠ не удалось отправить {chat_id} ({name})")


if __name__ == "__main__":
    main()