# Changelog

Все значимые изменения проекта MAX Bot.

## [3.0.0] — 2026-10-14

### ✨ Добавлено

**Веб-интерфейс (`web/`)**
- FastAPI + Jinja2 + uvicorn, порт `9118`
- Sidebar со списком чатов, шапка с синхронизацией
- Отправка текста, вложений (file/image/video/audio)
- Редактирование и удаление сообщений
- Двусторонняя синхронизация с MAX
- **Пересылка** сообщений (`↪️ Переслать` в меню)
- **Пометка админского чата** 👑
- Emoji-picker (`@emoji-mart`)

**Вложения**
- Upload + Retry на `attachment.not.ready` (0/1/2/4/8 сек)
- **Enrich `url`** через `GET /messages?message_ids=<mid>`
- Превью: `<img>` для image, `<a href>` для file/video/audio
- Сохранение `attachments` в БД для входящих и исходящих

**Бот (`bot.py`)**
- Извлечение `attachments` из `GET /updates`
- Сохранение вложений для `TYPE_HERMES_REQ`, `TYPE_ANSWER`, `TYPE_SERVICE`

**Скрипты**
- `setup_bot.py`: показ **модели LLM**, очистка БД под новую схему
- `hermes_session_model.py`, `import_history.py`, `logs.sh`, `test_attach.py`

**Инфраструктура**
- `systemd/max-web.service` — новый
- `config.py.example` — шаблон с заглушками
- `requirements.lock` — точные версии

### 🔧 Изменено

- `shared/repository.py`: `update_attachments`, `insert_message(attachments=...)`
- `web/app.py`: enrich + retry
- `index.html`: модалка пересылки, 👑, условный рендер `m.text`, `<a href>`
- `style.css`: `.forward-modal*`, `.admin-badge`, `.attachment-*`
- `systemd/max-bot.service`: `Restart=on-failure`, `After=network-online.target`, `LANG/LC_ALL`

### 🐛 Исправлено

- Дублирование `📎 [file]` + `📄 filename`
- Задвоение ответа Hermes (`_ans` в БД)
- Двойная отправка утреннего при `msg_id=None`
- `attachment.not.ready` при отправке файлов
- Пустые записи в БД для входящих с вложениями

### ⚠️ Известные ограничения

- **Пересылка** работает **только для текста**
- Free-модели OpenRouter нестабильны (`404`)
- `seen_ids` в `bot.py` растёт бесконечно

### 🗑 Удалено

- Старые скрипты: `migrate_db.py`, `send_alerts.py`, `send_daily.py`, `test_send.py`, `test_send1.py`
- Старые systemd-сервисы: `max-send-alerts`, `max-send-daily`, `max-send-aphorism`
- Корневой `db.py`, `chat_messages.py`, `test_db.py` (заменены на `shared/`)


## [2.1.0] — 2026-10-09

### 🎉 Новое

- **`weather.py`** — модуль погоды с Яндекс.Погоды через HTML-парсинг (без API и без Hermes).
  - Координаты города определяются через Nominatim (OpenStreetMap).
  - Slug/GeoID города — автоматически через Яндекс.Погоду по координатам.
  - Парсинг скрытых `<p class="A11Y_visuallyHidden">` — температура, ощущается, ветер, влажность, давление, почасовой, прогноз.
  - Дополнительные страницы `/allergies` (пыльца) и `/magnetic-storms` (магнитное поле).
  - `--resolve yandex.ru:443:77.88.44.55` — обход проблемы с systemd-resolved.
  - Почасовой прогноз: с 09:00 локального времени, 12 записей.
  - Эмодзи-иконки погоды, снег → 🌨️.
  - Debug-логи через `WEATHER_DEBUG=1`.
- **`wish_worker`** в `bot.py` — отправляет пожелание (TypeID=2) после ответа на утреннее, независимо от времени.

### 🔧 Изменено

- `_send_weather` в `bot.py` — теперь вызывает `weather.get_weather(city)` вместо Hermes.
- Удалена `get_weather_for_chat` — больше не нужна.
- `db.py` — единая схема `MessagesDB` / `MessagesRel` (удалены старые `messages` / `messages_rel`).

### 🐛 Исправлено

- Дубли утренних сообщений — отключены `max-send-*.timer` (остатки старой архитектуры).
- Пожелание не уходило после ответа — исправлено через `wish_worker`.
- Погода падала с `HTTP 400` от YandexGPT — теперь полностью без Hermes.
- `--resolve` для yandex.ru — работает при отсутствии DNS.

### ⚠️ Известные ограничения

- Nominatim требует User-Agent и имеет лимит 1 запрос/сек (у нас кэш в памяти).
- Если Яндекс изменит вёрстку — регулярки могут отвалиться.
- Для Nominatim нужен доступ в интернет (не только к yandex.ru).