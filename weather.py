#!/usr/bin/env python3
# weather.py
"""
Погода с Яндекс.Погоды через HTML (без API).

Схема работы:
  1. Nominatim (OpenStreetMap) — координаты по названию города.
  2. Яндекс.Погода с ?lat=&lon= — отдаёт HTML с GeoID/slug города.
  3. Из HTML вытаскиваем slug/geoid → качаем страницу города.
  4. Парсим скрытые <p class="A11Y_visuallyHidden">.

Особенности:
  - curl с --resolve yandex.ru:443:77.88.44.55
  - почасовой: с 09:00 локального времени, 12 записей
  - защита от __next_error__
  - debug-логи через WEATHER_DEBUG=1
  - кэш координат и slug'ов в памяти
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime

YANDEX_IP = "77.88.44.55"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
BASE_URL = "https://yandex.ru/pogoda/ru"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "max-bot/1.0 (https://github.com/)"

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг",
            "Пятница", "Суббота", "Воскресенье"]

# ── Debug-логирование ────────────────────────────────────────────
_DEBUG = os.environ.get("WEATHER_DEBUG", "").lower() in ("1", "true", "yes")


def _log(msg: str):
    if _DEBUG:
        print(msg)


# ── Кэши в памяти ────────────────────────────────────────────────
_COORD_CACHE: dict[str, tuple[float, float]] = {}
_SLUG_CACHE: dict[str, str] = {}


# ── Маппинг описаний → эмодзи ────────────────────────────────────
ICON_MAP = [
    ("небольшой снег", "🌨️"),
    ("небольшой дождь", "🌦"),
    ("снег с дождём", "🌨️"),
    ("снег с дожем", "🌨️"),
    ("облачно с прояснениями", "⛅"),
    ("малооблачно", "🌤"),
    ("переменная облачность", "⛅"),
    ("ливень", "🌧"),
    ("гроза", "⛈"),
    ("дождь", "🌧"),
    ("снег", "🌨️"),
    ("ясно", "☀️"),
    ("облачно", "☁️"),
    ("пасмурно", "☁️"),
    ("туман", "🌫"),
    ("дымка", "🌫"),
]

POLLEN_MAP = [
    ("не летает, не раздражает", "Нет риска аллергии"),
    ("не летает", "Нет риска аллергии"),
    ("нет риска", "Нет риска аллергии"),
    ("низкий", "Низкий риск"),
    ("средний", "Средний риск"),
    ("высокий", "Высокий риск"),
    ("очень высокий", "Очень высокий риск"),
]


# ────────────────────────────────────────────────────────────
#  Утилиты
# ────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u200b", "").replace("\u2060", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _num_sign(s: str) -> str:
    if s in (None, "", "?"):
        return "?°C"
    return f"{s}°C"


def icon_for(condition: str) -> str:
    c = (condition or "").strip().lower()
    for key, icon in sorted(ICON_MAP, key=lambda x: -len(x[0])):
        if key in c:
            return icon
    return "☁️"


def normalize_pollen(s: str) -> str:
    s_lc = _clean(s).lower()
    for key, val in POLLEN_MAP:
        if key in s_lc:
            return val
    return _clean(s)


# ────────────────────────────────────────────────────────────
#  Nominatim: координаты по названию города
# ────────────────────────────────────────────────────────────

def get_coordinates(city: str) -> tuple[float, float] | None:
    """
    Возвращает (lat, lon) для города через Nominatim.
    Кэширует результат в памяти.
    """
    if city in _COORD_CACHE:
        return _COORD_CACHE[city]

    params = urllib.parse.urlencode({
        "q": city,
        "format": "json",
        "limit": 1,
        "accept-language": "ru",
    })
    url = f"{NOMINATIM_URL}?{params}"

    req = urllib.request.Request(url, headers={
        "User-Agent": NOMINATIM_UA,
        "Accept-Language": "ru-RU,ru;q=0.9",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data:
            _log(f"[weather] Nominatim: '{city}' не найден")
            return None
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        _COORD_CACHE[city] = (lat, lon)
        _log(f"[weather] Nominatim: {city} → ({lat}, {lon})")
        return lat, lon
    except Exception as e:
        _log(f"[weather] Nominatim error для '{city}': {e}")
        return None


# ────────────────────────────────────────────────────────────
#  Скачивание
# ────────────────────────────────────────────────────────────

def fetch_html_by_url(url: str) -> str:
    """Качает произвольный URL с подменой DNS для yandex.ru."""
    cmd = [
        "curl", "-sL", "--max-time", "25",
        "--resolve", f"yandex.ru:443:{YANDEX_IP}",
        "-A", USER_AGENT,
        "-H", "Accept-Language: ru-RU,ru;q=0.9",
        "-H", "Accept: text/html,application/xhtml+xml",
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            _log(f"[weather] curl rc={r.returncode}: {r.stderr[:200]}")
            return ""
        return r.stdout
    except subprocess.TimeoutExpired:
        _log("[weather] curl timeout")
        return ""
    except Exception as e:
        _log(f"[weather] curl error: {e}")
        return ""


def fetch_html(slug: str, extra_path: str = "") -> str:
    """Качает страницу Яндекс.Погоды по slug."""
    url = f"{BASE_URL}/{slug}{extra_path}"
    return fetch_html_by_url(url)


# ────────────────────────────────────────────────────────────
#  Определение slug по координатам
# ────────────────────────────────────────────────────────────

def resolve_slug(city: str) -> str | None:
    """
    Определяет slug города:
      1. Nominatim → координаты
      2. Яндекс.Погода с ?lat=&lon= → HTML
      3. Из HTML вытаскиваем slug/geoid.
    Приоритет: GeoID (число) — это ссылка на текущий город.
    Кэширует результат в памяти.
    """
    if city in _SLUG_CACHE:
        return _SLUG_CACHE[city]

    coords = get_coordinates(city)
    if not coords:
        return None

    lat, lon = coords
    url = f"{BASE_URL}?lat={lat}&lon={lon}"
    html = fetch_html_by_url(url)

    if not html or len(html) < 10000:
        _log(f"[weather] Пустой HTML при resolve_slug для '{city}'")
        return None

    # Приоритет 1: GeoID (число) — это ссылка на САМ город
    # В HTML первое вхождение /pogoda/ru/<geoid> — это текущий город
    m = re.search(r'/pogoda/ru/(\d+)\b', html)
    if m:
        slug = m.group(1)
        _SLUG_CACHE[city] = slug
        _log(f"[weather] {city} → slug={slug} (geoid)")
        return slug

    # Приоритет 2: буквенный slug
    SERVICE = {
        "allergies", "magnetic-storms", "maps", "month",
        "moon", "pressure", "sources", "uv-index", "blog",
        "details", "search", "10-days", "tomorrow", "weekend",
    }
    candidates = re.findall(r'/pogoda/ru/([a-z][a-z-]+)', html)
    for c in candidates:
        if c not in SERVICE:
            _SLUG_CACHE[city] = c
            _log(f"[weather] {city} → slug={c} (text)")
            return c

    _log(f"[weather] Не нашли slug для '{city}' в HTML")
    return None

# ────────────────────────────────────────────────────────────
#  Парсинг
# ────────────────────────────────────────────────────────────

def parse_main(html: str, city: str) -> dict:
    data = {}

    # --- 1. Полное описание погоды сейчас ---
    m = re.search(
        r'<p class="A11Y_visuallyHidden[^>]*>\s*'
        r'[^<]*?погода сейчас:\s*([^<]+)',
        html,
    )
    main_text = _clean(m.group(1)) if m else ""

    if main_text:
        cond_m = re.match(r"([^.]+)\.", main_text)
        data["condition"] = cond_m.group(1).strip() if cond_m else ""

    m = re.search(r"Температура воздуха ([+-]?\d+)°", main_text)
    data["temp"] = m.group(1) if m else "?"

    m = re.search(r"ощущается как ([+-]?\d+)°", main_text)
    data["feels"] = m.group(1) if m else "?"

    m = re.search(r"Скорость ветра ([\d.,]+)\s*м/с,\s*([^.]+)", main_text)
    if m:
        data["wind"] = m.group(1).replace(",", ".")
        data["wind_dir"] = m.group(2).strip()
    else:
        data["wind"] = "?"
        data["wind_dir"] = ""

    m = re.search(r"Давление (\d+)\s*мм рт\. ст\.", main_text)
    data["pressure"] = m.group(1) if m else "?"

    m = re.search(r"Влажность (\d+)%", main_text)
    data["humidity"] = m.group(1) if m else "?"

    m = re.search(r"Прогноз погоды на сегодня:\s*([^<]+)", html)
    data["forecast_today"] = _clean(m.group(1)) if m else ""

    # --- 2. Почасовой прогноз ---
    hourly_raw = re.findall(
        r'<p class="A11Y_visuallyHidden[^>]*>\s*'
        r'(?:[а-яА-Я]+, )?'
        r'(\d{2}:\d{2}):\s*'
        r'([+-]?\d+)°,\s*'
        r'([^,]+),\s*'
        r'Ощущается как ([+-]?\d+)°',
        html,
    )

    hourly_all = []
    seen = set()
    for hhmm, t, cond, feels in hourly_raw:
        if hhmm in seen:
            continue
        seen.add(hhmm)
        hourly_all.append({
            "time": hhmm,
            "temp": t,
            "condition": _clean(cond),
            "feels": feels,
        })

    start_idx = 0
    for i, h in enumerate(hourly_all):
        try:
            hh = int(h["time"].split(":")[0])
        except ValueError:
            continue
        if hh >= 9:
            start_idx = i
            break

    data["hourly"] = hourly_all[start_idx:start_idx + 12]

    return data


def parse_allergies(html: str) -> str:
    if not html:
        return "нет данных"
    patterns = [
        r"([А-Яа-я ,]+не раздражает[А-Яа-я ,]*)",
        r"(Нет риска аллергии)",
        r"(Низкий риск)",
        r"(Средний риск)",
        r"(Высокий риск)",
        r"(Очень высокий риск)",
        r"(Умеренный риск)",
        r"риск аллергии[:\s]+([^<.]+)",
        r"[Пп]ыльца[^<.]*?[:\s]+([^<.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = _clean(m.group(1))
            if val:
                return val
    return "нет данных"


def parse_magnetic(html: str) -> str:
    if not html:
        return "нет данных"
    patterns = [
        r"(спокойное)",
        r"(небольшие возмущения)",
        r"(слабая буря)",
        r"(средняя буря)",
        r"(сильная буря)",
        r"(очень сильная буря)",
        r"(слабо возмущённое)",
        r"(возмущённое)",
        r"(магнитная буря)",
        r"[Мм]агнитное поле[:\s]+([^<.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = _clean(m.group(1)).lower()
            if val:
                return val
    return "нет данных"


# ────────────────────────────────────────────────────────────
#  Форматирование
# ────────────────────────────────────────────────────────────

def format_message(city: str, data: dict) -> str:
    now = datetime.now()
    day = now.strftime("%d.%m")
    weekday = WEEKDAYS[now.weekday()]

    lines = []
    lines.append(f"🌤 {city}, {day} ({weekday})")
    lines.append("")

    lines.append(f"🌡 Температура: {_num_sign(data.get('temp', '?'))}")
    lines.append(f"🤗 Ощущается: {_num_sign(data.get('feels', '?'))}")
    lines.append(f"☁️ Погода: {(data.get('condition') or '—').lower()}")
    lines.append(f"💨 Ветер: {data.get('wind', '?')} м/с")
    lines.append(f"💧 Влажность: {data.get('humidity', '?')}")
    lines.append(f"📊 Давление: {data.get('pressure', '?')} мм рт. ст.")
    lines.append("")

    hourly = data.get("hourly") or []
    if hourly:
        lines.append("📈 Почасовой прогноз:")
        for h in hourly:
            icon = icon_for(h["condition"])
            t = h["temp"]
            f = h["feels"]
            cond = h["condition"].lower()
            lines.append(f"{icon} {h['time']} {t}° ({f}°) {cond}")
        lines.append("")

    pollen = normalize_pollen(data.get("pollen", "нет данных"))
    magnetic = data.get("magnetic", "нет данных")
    lines.append(f"🌿 Пыльца: {pollen}")
    lines.append(f"🧲 Магнитное поле: {magnetic}")
    lines.append("")

    forecast = (data.get("forecast_today") or "").strip()
    if forecast:
        if "·" in forecast:
            forecast = forecast.split("·")[0].strip()
        lines.append(f"☂️ Прогноз: {forecast}")

    return "\n".join(lines).rstrip()


# ────────────────────────────────────────────────────────────
#  Публичная функция
# ────────────────────────────────────────────────────────────

def get_weather(city: str) -> str | None:
    """
    Собирает погоду для города.
    Slug определяется автоматически (Nominatim + Яндекс.Погода).
    """
    slug = resolve_slug(city)
    if not slug:
        print(f"[weather] Не удалось найти slug для '{city}'")
        return None

    html = fetch_html(slug)
    if not html or len(html) < 10000:
        print(f"[weather] Маленький HTML для {city} ({slug}): {len(html)} байт")
        return None

    if "__next_error__" in html[:500]:
        print(f"[weather] ❌ Яндекс __next_error__ для {city} (slug='{slug}')")
        return None

    data = parse_main(html, city)

    try:
        allergies_html = fetch_html(slug, "/allergies")
        data["pollen"] = parse_allergies(allergies_html)
    except Exception as e:
        _log(f"[weather] allergies error: {e}")
        data["pollen"] = "нет данных"

    try:
        magnetic_html = fetch_html(slug, "/magnetic-storms")
        data["magnetic"] = parse_magnetic(magnetic_html)
    except Exception as e:
        _log(f"[weather] magnetic error: {e}")
        data["magnetic"] = "нет данных"

    return format_message(city, data)


# ────────────────────────────────────────────────────────────
#  CLI для теста
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    city = sys.argv[1] if len(sys.argv) > 1 else "Санкт-Петербург"

    print(f"🌤 {city}")
    print("─" * 50)

    text = get_weather(city)
    if text:
        print(text)
    else:
        print("❌ Не удалось получить погоду")