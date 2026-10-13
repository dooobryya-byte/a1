# send_aphorism.py
"""
Афоризмы дня с anekdot.ru.

Новый формат (2026): https://www.anekdot.ru/release/aphorism/day/
Публичная функция:
    get_aphorism() -> str | None
"""
import random
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


def now_str():
    return datetime.now().strftime("%H:%M:%S")


BASE_URL = "https://www.anekdot.ru/release/aphorism/day"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _fetch_html(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.text
        print(f"[{now_str()}] ⚠ anekdot: HTTP {r.status_code} для {url}")
    except requests.RequestException as e:
        print(f"[{now_str()}] ⚠ anekdot: {type(e).__name__}: {e}")
    return None


def _parse_aphorisms(html: str) -> list[str]:
    """Извлекает афоризмы из HTML новой страницы anekdot.ru."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    aphorisms = []

    # На новой странице афоризмы в <div class="topicbox">
    for box in soup.find_all("div", class_="topicbox"):
        # Текст внутри <div class="text">
        text_div = box.find("div", class_="text")
        if not text_div:
            continue

        text = text_div.get_text("\n", strip=True)
        if not text:
            continue

        # Чистим
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Фильтр: убираем "СсылкаПоделиться", рейтинги, короткие обрывки
        if "Поделиться" in text or "Ссылка" in text:
            continue

        if 20 <= len(text) <= 500:
            aphorisms.append(text)

    return aphorisms


def _get_for_date(date: datetime) -> list[str]:
    """Афоризмы на конкретную дату (YYYY-MM-DD)."""
    date_str = date.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{date_str}/"

    html = _fetch_html(url)
    if not html:
        return []

    return _parse_aphorisms(html)


def get_aphorism() -> str | None:
    """
    Возвращает один случайный афоризм.

    Логика:
      1. Начинаем сразу со вчерашнего дня (сегодня обычно ещё не опубликован).
      2. Fallback: до 8 дней назад.
      3. Если нигде ничего — возвращает None.
    """
    today = datetime.now()

    # Сразу со вчера (сегодня обычно 404)
    for i in range(1, 9):        # 1..8 дней назад
        date = today - timedelta(days=i)
        aphorisms = _get_for_date(date)
        if aphorisms:
            print(f"[{now_str()}] 📖 афоризм с {date.strftime('%d.%m.%Y')} "
                  f"({len(aphorisms)} шт.)")
            return random.choice(aphorisms)

    print(f"[{now_str()}] ⏭ афоризм не найден за последние 8 дней")
    return None

if __name__ == "__main__":
    print("Тест get_aphorism()")
    print("─" * 50)
    a = get_aphorism()
    if a:
        print(a)
    else:
        print("❌ None")