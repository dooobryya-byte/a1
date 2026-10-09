<div align="center">

# 🤖 MAX Bot — Say Me Hello Today

**Telegram-подобный бот для мессенджера MAX через GREEN-API**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![GREEN-API](https://img.shields.io/badge/GREEN--API-MAX-25D366?style=for-the-badge)](https://green-api.com/)
[![Hermes](https://img.shields.io/badge/Hermes-AI%20Agent-8B5CF6?style=for-the-badge)](https://github.com/)

*Утренние приветствия • Погода • Афоризмы дня • Мост к AI-агенту Hermes*

</div>

---

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| ☀️ **Утреннее приветствие** | Индивидуальное время для каждого чата. Рандомный текст из `DAILY_QUESTION_MESSAGES_M/F` (по роду) |
| 💬 **Ответ на приветствие** | После ответа пользователя — пожелание хорошего дня (`ANSWER_MESSAGES_M/F`) |
| 🌤 **Погода (своя)** | Парсинг Яндекс.Погоды через `weather.py`, координаты — Nominatim, slug — автоматически |
| 📖 **Афоризм дня** | Парсинг `anekdot.ru` (сегодня, fallback — до 7 дней назад) |
| 🔔 **Warning молчунам** | Если нет ответа до `alert_hour` — предупреждение + сигнал админу |
| 🤖 **Мост к Hermes** | `/hermes <вопрос>` или `❇ <вопрос>` — общение с AI-агентом |
| 🎭 **Разделение по роду** | Мужской (`_M`) / женский (`_F`) наборы текстов |
| 💾 **Состояние в БД** | SQLite (`bot_state.db`), переживает перезапуск |

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        MAX (GREEN-API)                          │
│                     аккаунт: Your_Max_Mobile                    │
└─────────────────────────┬───────────────────────────────────────┘
                          │ webhook / polling
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  bot.py (systemd service, постоянный процесс)                   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ daily_worker │  │ alert_worker │  │ hermes_worker      │    │
│  │ (утро)       │  │ (warning)    │  │ (запросы к Hermes) │    │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘    │
│         │                 │                    │                │
│         └─────────────────┴────────────────────┘                │
│                           │                                     │
│                  ┌────────▼────────┐                            │
│                  │  db.py (SQLite) │                            │
│                  │  · MessagesDB   │                            │
│                  │  · MessagesRel  │                            │
│                  └────────┬────────┘                            │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  Hermes AI Agent      │
                │  сессии: max_<chatId> │
                └───────────────────────┘
```

### 📦 Компоненты

| Файл | Роль |
|------|------|
| **`bot.py`** | 🎯 Основной слушатель + воркеры (`daily`, `alert`, `hermes`) |
| **`db.py`** | 💾 Модуль SQLite: `MessagesDB` + `MessagesRel` |
| **`send_aphorism.py`** | 📖 Парсер `anekdot.ru` с fallback на 7 дней |
| **`utils.py`** | ⏰ `is_time_to_send()` — общая проверка времени |
| **`config.py`** | ⚙️ Все настройки: чаты, города, времена, тексты |
| **`setup_bot.py`** | 🛠️ Менеджер сессий Hermes и очистка БД |
| **`debug_db.py`** | 🔍 Просмотр содержимого БД |
| **`weather.py`** | 🌤 Модуль погоды: Nominatim → Яндекс.Погода → парсинг |

---

## 📊 Схема БД

### 🗂️ MessagesDB — все сообщения

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | INTEGER PK | автоинкремент |
| `message_datetime` | TEXT | дата/время сообщения |
| `chat_id` | TEXT | Allowed Max Chat ID |
| `id_message` | TEXT | ID сообщения в MAX (`0` — для ответов Hermes) |
| `message_text` | TEXT | текст |
| `type_id` | INTEGER | тип (см. ниже) |

### 🔗 MessagesRel — связки «запрос ↔ ответ»

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | INTEGER PK | автоинкремент |
| `message_datetime` | TEXT | дата/время создания связки |
| `chat_id` | TEXT | ID чата |
| `id_message_for` | TEXT | ID сообщения, на которое ответили |
| `id_message_back` | TEXT | ID ответа (`0` — для ответов Hermes) |

### 🏷️ TypeID — типы сообщений

| ID | Название | Требует ответа? | Мониторинг |
|:--:|----------|:---------------:|:----------:|
| **0** | ☀️ Утреннее приветствие | ✅ (→ 1) | каждую минуту |
| **1** | 💬 Ответ пользователя | ✅ (→ 2) | каждую минуту |
| **2** | 🎁 Пожелание хорошего дня | ❌ | — |
| **3** | 🔔 Warning молчуну | ❌ | — |
| **4** | 📢 Сигнал админу | ❌ | — |
| **5** | 🤖 Запрос к Hermes | ✅ (→ 7) | каждые 5 сек |
| **7** | ⏳ Ожидание Hermes | ✅ (→ 8) | до `HERMES_TIMEOUT` |
| **8** | ✅ Ответ Hermes | ❌ | — |
| **9** | 🗑️ Служебное / вне цикла | ❌ | — |

---

## 🚀 Установка на Ubuntu 24.04

### 1️⃣ Системные зависимости

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

### 2️⃣ Клонировать репозиторий

```bash
cd ~
git clone git@github.com:USERNAME/max-bot.git
cd max-bot
```

### 3️⃣ Создать venv и установить зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4️⃣ Настроить `config.py`

```bash
cp config.py.example config.py
nano config.py
```

**Заполнить:**

```python
ID_INSTANCE = "3100xxxxxxx"           # из GREEN-API
API_TOKEN = "abcdef123..."             # из GREEN-API

ALLOWED_CHATS = {
    "Your_ID1": {
        "name": "Your_Name1",
        "gender": "m",
        "city": "Your_City1",
        "morning_hour": 9,
        "morning_minute": 0,
        "alert_hour": 13,
        "alert_minute": 0,
    },
    # ... остальные чаты
}

ADMIN_CHAT_ID = "Your_ID"
ADMIN_NAME = "Your_Name"
HERMES_CMD = "/home/user/.local/bin/hermes"
```

### 5️⃣ Проверить работу

```bash
source venv/bin/activate

# Проверка импортов
python -c "import bot; print('bot OK')"
python -c "import db; print('db OK')"

# Проверка Hermes-сессий, очистка БД
python setup_bot.py

# Тестовый запуск бота
python bot.py
# Ctrl+C для выхода
```

### 6️⃣ Установить systemd-юнит

```bash
sudo cp systemd/max-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now max-bot.service
```

### 7️⃣ Проверить

```bash
sudo systemctl status max-bot
journalctl -u max-bot -f -q
```

---

## 🔧 Управление

### 🎛️ `setup_bot.py` — менеджер

```bash
python setup_bot.py
```

| Пункт | Что делает |
|:-----:|-----------|
| **1** | ✅ Проверка наличия сессий `max_*` |
| **2** | 🛠️ Создание / исправление сессий Hermes |
| **3** | 📋 Показать все сессии Hermes |
| **4** | 🗑️ Удаление сессий (интерактивный выбор) |
| **5** | 🧹 Очистка БД (`MessagesDB` + `MessagesRel`) |

### 💻 Команды бота

| Команда | Где | Что делает |
|---------|-----|-----------|
| `/hermes <вопрос>` | от админа | Запрос к AI-агенту Hermes |
| `❇ <вопрос>` | от админа | То же (альтернативный префикс) |
| `/hermes -command <shell>` | от админа | Выполнение shell-команды |

### 📅 Времена (индивидуально для каждого чата)

| chatId | Имя | Утро | Warning |
|:------:|-----|:----:|:-------:|
| `Your_ID1` | Your_Name1 | 09:00 | 13:00 |
| `Your_ID2` | Your_Name2 | 07:00 | 11:00 |
| `Your_ID3` | Your_Name3 | 09:00 | 15:00 |

---

## 📖 Логика работы

### 🌅 Утренний цикл

```
09:00 ── send ──▶ Утреннее приветствие (TypeID=0)
                  │
      ┌───────────┴───────────┐
      │                       │
      ▼                       ▼
  Ответ до 13:00        Молчание до 13:00
      │                       │
      ▼                       ▼
  TypeID=1              Warning (TypeID=3)
      │                       │
      ▼                       ▼
  Пожелание (TypeID=2)   Сигнал админу (TypeID=4)
      │
      ▼
  🌤 Погода от Hermes
      │
      ▼
  📖 Афоризм дня
```

### 🤖 Мост к Hermes

```
/hermes привет
      │
      ▼
TypeID=5 (запрос)
      │
      ▼
⏳ Думаю... (TypeID=7)
      │
      ▼
Hermes генерирует ответ (в отдельном потоке)
      │
      ▼
✏️ editMessage ⏳ → ответ
      │
      ▼
TypeID=8 (ответ Hermes)
```

---

## 🛠️ Полезные команды

### 📜 Логи

```bash
# Бот — в реальном времени
journalctl -u max-bot -f -q

# Последние 50 строк
journalctl -u max-bot -n 50 -q

# Только ошибки
journalctl -u max-bot -p err -q

# Логи за сегодня
journalctl -u max-bot --since today -q
```

### 💾 БД

```bash
# Просмотр содержимого
python debug_db.py

# Для конкретного чата
python debug_db.py 8627605

# Очистка (с бэкапом)
python setup_bot.py    # пункт 5
```

### 🔄 Перезапуск

```bash
sudo systemctl restart max-bot
sudo systemctl status max-bot --no-pager | head -8
```

---

## 🐛 Решение проблем

<details>
<summary><b>❌ Бот зацикливается на сообщениях</b></summary>

**Симптом:** `⏳ Думаю...` → `⚠️ Hermes код 2:` → `⏳ Думаю...` → ...

**Причина:** бот видит свои же исходящие сообщения как входящие.

**Решение:**
- Проверь `get_messages()` — фильтр `type == "incoming"` и `senderId != INSTANCE_WID`.
- Проверь `INSTANCE_WID` — запусти `python -c "from bot import get_instance_wid; print(get_instance_wid())"`.
- Очисти очередь GREEN-API:
  ```bash
  curl -X DELETE "https://3100.api.green-api.com/waInstance{ID}/clearWebhooksQueue/{TOKEN}"
  ```
</details>

<details>
<summary><b>❌ Hermes: No session found matching 'max_*****'</b></summary>

**Симптом:** `hermes код 1: No session found matching 'max_8627605'`.

**Причина:** сессия не создана или title не совпадает.

**Решение:**
1. Запусти `python setup_bot.py`.
2. Пункт 1 — проверить.
3. Пункт 2 — создать/исправить.
4. Пункт 1 — убедиться, что все ✅.
</details>

<details>
<summary><b>❌ Афоризм не приходит</b></summary>

**Симптом:** после пожелания приходит только погода, без афоризма.

**Причина:** `anekdot.ru` не опубликовал афоризмы за сегодня (обычно появляются днём).

**Решение:** `get_aphorism()` уже имеет **fallback на 7 дней назад**. Проверь:
```bash
python3 -c "from send_aphorism import get_aphorism; print(get_aphorism())"
```
Если `None` — проблема в парсере или сайт недоступен.
</details>

<details>
<summary><b>❌ Webhook не приходит</b></summary>

**Симптом:** бот не реагирует на сообщения в MAX.

**Решение:**
1. Проверь настройки GREEN-API:
   ```bash
   curl "https://3100.api.green-api.com/waInstance{ID}/getSettings/{TOKEN}" | python3 -m json.tool
   ```
   Убедись, что `incomingWebhook: yes` и `webhookUrl: ""`.
2. Очисти очередь:
   ```bash
   curl -X DELETE "https://3100.api.green-api.com/waInstance{ID}/clearWebhooksQueue/{TOKEN}"
   ```
</details>

---

## 📋 Requirements

```
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
```

---

## 📁 Структура проекта

```
~/max-bot/
├── bot.py                  # 🎯 основной бот + воркеры
├── db.py                   # 💾 SQLite модуль
├── config.py               # ⚙️ настройки (не в git)
├── config.py.example       # ⚙️ шаблон
├── send_aphorism.py        # 📖 парсер афоризмов
├── utils.py                # ⏰ is_time_to_send()
├── setup_bot.py            # 🛠️ менеджер сессий + очистка БД
├── debug_db.py             # 🔍 просмотр БД
├── bot_state.db            # 💾 БД (создаётся автоматически)
├── requirements.txt
├── README.md
└── systemd/
    └── max-bot.service     # systemd-юнит
```

---

## 📄 Лицензия

MIT — используй свободно.

---

<div align="center">

**Сделано с ❤️ для мессенджера MAX**

⭐ Поставь звезду, если проект полезен!

</div>